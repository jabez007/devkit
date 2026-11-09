"""Delivery contracts with real Git and a scripted tool adapter, not live qualification."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "integrations/gascity/odoo/assets"
BASE = ROOT / "integrations/gascity/base/assets"


def git(project, *args):
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            *args,
        ],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    )
    return result.stdout.strip()


@pytest.fixture
def checks(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE))
    spec = importlib.util.spec_from_file_location("odoo_pack_checks", ASSETS / "checks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def job(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "tracked").write_text("base\n")
    git(project, "init", "-q", "--initial-branch=devkit/task")
    git(project, "add", ".")
    git(project, "commit", "-qm", "Base")
    control = tmp_path / "tools.json"
    control.write_text(json.dumps({"modules": ["sale_demo", "stock_demo"]}))
    tool = tmp_path / "runner.py"
    tool.write_text(r"""
import json, os, pathlib, sys
control = pathlib.Path(sys.argv[1])
mode = json.loads(control.read_text())
args = sys.argv[2:]
with control.with_suffix('.calls').open('a') as stream:
    stream.write(json.dumps(args) + '\n')
if mode.get('mutate'):
    pathlib.Path('tracked').write_text('changed during check')
if mode.get('invalid'):
    print('not JSON')
    sys.exit(0)
name = 'static' if args[0] == 'devkit-odoo' else args[args.index('run') + 1]
status = 'failed' if mode.get('red') == name else 'success'
data = {'inspection_complete': True, 'modules': [
    {'module': name, 'status': 'bumped'} for name in mode.get('modules', [])]}
result = dict(status=status, summary='Scripted tool result', reason=None, data=data)
print(json.dumps(result if name == 'static' else {
    'result': result, 'run_id': 'fixture-run', 'evidence_path': '/fixture/evidence.json'}))
sys.exit(0 if status == 'success' or mode.get('wrong_exit') else 1)
""")
    return {
        "project": str(project),
        "base_commit": git(project, "rev-parse", "HEAD"),
        "addons_paths": ["custom addons"],
        "runner": [sys.executable, str(tool), str(control)],
        "artifacts": str(tmp_path / "artifacts"),
    }, control


def run(checks, job, mode=None):
    config, control = job
    if mode is not None:
        control.write_text(json.dumps(mode))
    checks.validate(config)
    result = checks.run(config, {"sha256": "b" * 64, "task_id": "task-one"})
    assert json.loads((Path(result["directory"]) / "results.json").read_text()) == result
    calls = [json.loads(line) for line in control.with_suffix(".calls").read_text().splitlines()]
    return result, calls


def test_all_changed_addons_receive_fresh_static_and_runtime_checks(checks, job):
    result, calls = run(checks, job)
    assert result["status"] == "success", result
    assert result["commit"] == job[0]["base_commit"]
    assert [item["name"] for item in result["checks"]] == [
        "versions",
        "static-sale_demo",
        "static-stock_demo",
        "runtime-sale_demo",
        "runtime-stock_demo",
    ]
    assert len(calls) == 5
    static = [args for args in calls if args[0] == "devkit-odoo"]
    assert [args[args.index("--module") + 1] for args in static] == ["sale_demo", "stock_demo"]
    assert all(args[args.index("--install-mode") + 1] == "fresh" for args in static)
    assert result["checks"][0]["evidence_path"] == "/fixture/evidence.json"


@pytest.mark.parametrize("command", ["static", "odoo.module.version.check"])
def test_red_gate_never_runs_native_runtime(checks, job, command):
    result, calls = run(checks, job, {"modules": ["sale_demo"], "red": command})
    assert result["status"] == "failed"
    assert all("odoo.module.test" not in args for args in calls)


def test_native_test_failure_is_red(checks, job):
    result, _ = run(checks, job, {"modules": ["sale_demo"], "red": "odoo.module.test"})
    assert result["status"] == "failed"


@pytest.mark.parametrize(
    "mode,reason",
    [
        ({"modules": []}, "NO_CHANGED_ADDONS"),
        ({"modules": ["same", "same"]}, "AMBIGUOUS_ADDON_NAMES"),
        ({"modules": ["bad-name"]}, "AMBIGUOUS_ADDON_NAMES"),
        ({"invalid": True}, "INVALID_CHECK_OUTPUT"),
        ({"red": "odoo.module.version.check", "wrong_exit": True}, "INVALID_CHECK_OUTPUT"),
        ({"modules": ["sale_demo"], "mutate": True}, "COMMIT_CHANGES_BEFORE_CHECKS"),
    ],
)
def test_incomplete_or_mutated_checks_cannot_pass(checks, job, mode, reason):
    result, _ = run(checks, job, mode)
    assert (result["status"], result["reason"]) == ("blocked", reason)


def test_dirty_worktree_runs_no_checks(checks, job):
    Path(job[0]["project"], "untracked").write_text("dirty")
    with pytest.raises(checks.DeliveryError, match="COMMIT_CHANGES_BEFORE_CHECKS"):
        checks.run(job[0], {})
    assert not job[1].with_suffix(".calls").exists()


def test_inherited_git_overrides_cannot_redirect_checks(checks, job, monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/missing/git")
    monkeypatch.setenv("GIT_WORK_TREE", "/missing/tree")
    result, _ = run(checks, job)
    assert result["status"] == "success"


@pytest.mark.parametrize(
    "key,value",
    [
        ("addons_paths", ["../outside"]),
        ("addons_paths", []),
        ("runner", "sh"),
        ("base_commit", "main"),
        ("extra_flags", []),
    ],
)
def test_invalid_operator_inputs_are_rejected(checks, job, key, value):
    job[0][key] = value
    with pytest.raises(checks.DeliveryError, match="INVALID_JOB"):
        checks.validate(job[0])


def test_artifacts_must_stay_outside_clean_project(checks, job):
    job[0]["artifacts"] = str(Path(job[0]["project"]) / "evidence")
    with pytest.raises(checks.DeliveryError, match="INVALID_JOB"):
        checks.validate(job[0])


@pytest.fixture
def pull_request(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE))
    spec = importlib.util.spec_from_file_location("odoo_pull_request", BASE / "delivery_pr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("DEVKIT_UNATTENDED", raising=False)
    return module


def report(checks, job, pull_request):
    bundle, _ = run(checks, job)
    brief = dict(
        problem="A fresh installation fails.",
        acceptance_criteria=["Delivery access installs successfully."],
        open_questions=["Should existing roles gain access?"],
    )
    return pull_request.prepare(job[0], bundle["brief"], bundle, brief)


def test_reviewable_body_contains_exact_checked_revision_and_questions(checks, job, pull_request):
    result = report(checks, job, pull_request)
    assert result["commit"] in result["body"]
    assert "runtime-stock_demo: success" in result["body"]
    assert "Should existing roles gain access?" in result["body"]
    assert Path(result["body_file"]).read_text() == result["body"]


@pytest.mark.parametrize(
    "unattended,approved,reason",
    [
        (True, True, "HUMAN_PUBLICATION_REQUIRED"),
        (False, False, "PR_BODY_APPROVAL_REQUIRED"),
    ],
)
def test_publication_needs_human_body_approval(
    checks, job, pull_request, monkeypatch, unattended, approved, reason
):
    result = report(checks, job, pull_request)
    if unattended:
        monkeypatch.setenv("DEVKIT_UNATTENDED", "")
    digest = result["body_sha256"] if approved else "wrong"
    with pytest.raises(pull_request.DeliveryError, match=reason):
        pull_request.publish(job[0], result, digest)


def test_changed_commit_cannot_use_passing_checks(checks, job, pull_request):
    result = report(checks, job, pull_request)
    project = Path(job[0]["project"])
    (project / "tracked").write_text("unchecked change")
    git(project, "add", ".")
    git(project, "commit", "-qm", "Unchecked revision")
    with pytest.raises(pull_request.DeliveryError, match="CHECKED_COMMIT_CHANGED"):
        pull_request.publish(job[0], result, result["body_sha256"])


@pytest.fixture
def github_adapter(tmp_path, job, pull_request, monkeypatch):
    config, _ = job
    config["github"] = dict(
        repo="fixture/task",
        remote="origin",
        base="main",
        head="devkit/task",
        protected_branches=["release/*"],
    )
    git(config["project"], "remote", "add", "origin", "https://github.com/fixture/task.git")
    state = tmp_path / "github.json"
    tool = tmp_path / "gh"
    tool.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json, os, pathlib, sys
state = pathlib.Path(os.environ['FIXTURE_GITHUB_STATE'])
args = sys.argv[1:]
with state.with_suffix('.calls').open('a') as stream:
    stream.write(json.dumps(args) + '\n')
value = json.loads(state.read_text()) if state.exists() else {}
if args[:2] == ['pr', 'list']:
    print(json.dumps([value['pr']] if 'pr' in value else []))
elif args[:2] == ['pr', 'create']:
    assert '--draft' in args
    value['pr'] = dict(url='https://github.com/fixture/task/pull/1', isDraft=True, state='OPEN',
        headRefOid=value['commit'], title=args[args.index('--title') + 1],
        body=pathlib.Path(args[args.index('--body-file') + 1]).read_text())
    state.write_text(json.dumps(value))
    print(value['pr']['url'])
elif args[:2] == ['pr', 'view']:
    print(json.dumps(value['pr']))
elif args[:2] == ['pr', 'edit']:
    value['pr'].update(title=args[args.index('--title') + 1],
        body=pathlib.Path(args[args.index('--body-file') + 1]).read_text(),
        headRefOid=value['commit'])
    state.write_text(json.dumps(value))
    print(value['pr']['url'])
else:
    sys.exit(1)
"""
    )
    tool.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FIXTURE_GITHUB_STATE", str(state))
    real_git = pull_request.git
    pushes = []

    def local_git(project, *arguments):
        if arguments[0] == "push":
            pushes.append(arguments)
            return "fixture push"
        return real_git(project, *arguments)

    monkeypatch.setattr(pull_request, "git", local_git)
    return state, pushes


def test_confirmed_draft_publication_retries_without_duplicate_pr(
    checks, job, pull_request, github_adapter
):
    state, pushes = github_adapter
    result = report(checks, job, pull_request)
    state.write_text(json.dumps(dict(commit=result["commit"])))
    first = pull_request.publish(job[0], result, result["body_sha256"])
    second = pull_request.publish(job[0], result, result["body_sha256"])
    assert first == second
    assert first["draft"] is True
    assert pushes == [("push", "--", "origin", result["commit"] + ":refs/heads/devkit/task")]
    calls = [json.loads(line) for line in state.with_suffix(".calls").read_text().splitlines()]
    assert len([args for args in calls if args[:2] == ["pr", "create"]]) == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("isDraft", False),
        ("state", "CLOSED"),
        ("headRefOid", "unchecked"),
        ("body", "Changed body"),
    ],
)
def test_existing_pr_must_match_the_exact_approved_draft(
    checks, job, pull_request, github_adapter, key, value
):
    state, pushes = github_adapter
    result = report(checks, job, pull_request)
    state.write_text(json.dumps(dict(commit=result["commit"])))
    pull_request.publish(job[0], result, result["body_sha256"])
    remote = json.loads(state.read_text())
    remote["pr"][key] = value
    state.write_text(json.dumps(remote))
    with pytest.raises(pull_request.DeliveryError, match="PUBLISHED_PR_MISMATCH"):
        pull_request.publish(job[0], result, result["body_sha256"])
    assert len(pushes) == 1


def plant_filter(project, marker):
    git(project, "config", "filter.planted.clean", f"touch {marker}; cat")
    (project / ".git/info/attributes").write_text("* filter=planted\n")
    tracked = project / "tracked"
    os.utime(tracked, (1, 1))


def test_session_written_filter_never_runs_in_the_controller(job, pull_request):
    project = Path(job[0]["project"])
    marker = project.parent / "marker"
    plant_filter(project, marker)
    with pytest.raises(pull_request.DeliveryError, match="UNSAFE_GIT_CONFIG"):
        pull_request.commit(project)
    assert not marker.exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("core.sshCommand", "touch marker"),
        ("core.pager", "touch marker"),
        ("core.worktree", "/tmp/other"),
        ("credential.helper", "!touch marker"),
        ("remote.origin.pushurl", "https://example.invalid/other.git"),
        ("remote.origin.vcs", "planted"),
        ("remote.origin.receivepack", "touch marker"),
        ("url.https://example.invalid/.insteadOf", "https://github.com/"),
        ("include.path", "/tmp/planted"),
        ("includeIf.gitdir:/.path", "/tmp/planted"),
        ("alias.planted", "!touch marker"),
        ("push.gpgSign", "true"),
    ],
)
def test_controller_refuses_config_that_can_run_programs_or_redirect(job, pull_request, key, value):
    project = Path(job[0]["project"])
    git(project, "config", key, value)
    with pytest.raises(pull_request.DeliveryError, match="UNSAFE_GIT_CONFIG"):
        pull_request.commit(project)


def test_controller_inspects_per_worktree_config(job, pull_request):
    project = Path(job[0]["project"])
    git(project, "config", "extensions.worktreeConfig", "true")
    linked = project.parent / "linked"
    git(project, "worktree", "add", "-q", str(linked), "-b", "linked")
    git(linked, "config", "--worktree", "core.sshCommand", "touch marker")
    with pytest.raises(pull_request.DeliveryError, match="UNSAFE_GIT_CONFIG"):
        pull_request.commit(linked)


def test_controller_accepts_inert_repository_config(job, pull_request):
    project = Path(job[0]["project"])
    for key, value in (
        ("core.hooksPath", ".beads/hooks"),
        ("beads.role", "maintainer"),
        ("user.name", "Fixture"),
        ("remote.origin.url", "https://github.com/fixture/task.git"),
        ("remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"),
        ("remote.origin.gh-resolved", "base"),
        ("branch.devkit/task.remote", "origin"),
        ("branch.devkit/task.merge", "refs/heads/devkit/task"),
    ):
        git(project, "config", key, value)
    assert pull_request.commit(project) == git(project, "rev-parse", "HEAD")


def test_publication_refuses_an_added_push_destination(checks, job, pull_request, github_adapter):
    result = report(checks, job, pull_request)
    project = job[0]["project"]
    git(project, "config", "--add", "remote.origin.url", "https://example.invalid/other.git")
    with pytest.raises(pull_request.DeliveryError, match="GITHUB_REMOTE_MISMATCH"):
        pull_request.publish(job[0], result, result["body_sha256"])
    assert github_adapter[1] == []
