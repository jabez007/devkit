"""Tests for the installed distribution using documented Devkit entry points."""

import json
import os
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from threading import Event

import devkit_example
import pytest
from devkit.app import create_service
from devkit.contracts import CheckSpec, CommandResult, CommandSpec


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    config = tmp_path / "operator/devkit"
    config.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    (root / "devkit.toml").write_text(
        'plugins=["example"]\n[profiles]\nverify=["example.readme"]\n'
    )
    policy = config / "policy.toml"
    policy.write_text(
        f"[trusted_plugins]\ndevkit-example={json.dumps(version('devkit-example'))}\n"
        f'[commands."example.readme"]\nproject={json.dumps(str(root))}\n'
        'effects=["read_fs"]\nsurfaces=["python","cli","mcp"]\n'
    )
    policy.chmod(0o600)
    (root / "README.md").write_text("# Project\nClean text.\n")
    return root


def result(project, arguments=None, **options):
    envelope = create_service(project).execute("example.readme", arguments or {}, **options)
    stored = json.loads(Path(envelope["evidence_path"]).read_text())
    assert stored["result"] == envelope["result"]
    assert stored["run_id"] == envelope["run_id"]
    assert stored["project_root"] == str(project)
    return envelope["result"]


def test_registered_command_and_check(project):
    assert result(project)["data"] == {"lines": 2, "trailing_whitespace_lines": []}
    checked = create_service(project).execute("core.check", {"profile": "verify"})
    assert checked["result"]["status"] == "success"
    assert checked["result"]["data"]["checks"][0]["check"] == "example.readme"


def test_actionable_failure_and_alternate_filename(project):
    (project / "README.rst").write_text("Trailing space \n")
    failed = result(project, {"filename": "README.rst"})
    assert failed["status"] == "failed"
    assert failed["reason"] == "TRAILING_WHITESPACE"
    assert failed["data"]["trailing_whitespace_lines"] == [1]


def test_diagnostic_names_requested_file(project):
    blocked = result(project, {"filename": "README.rst"})
    assert blocked["reason"] == "README_UNAVAILABLE"
    assert "README.rst" in blocked["summary"]


@pytest.mark.parametrize("arguments", [{"filename": "../secret"}, {"unknown": True}])
def test_invalid_input(project, arguments):
    assert result(project, arguments)["reason"] == "INVALID_INPUT"


@pytest.mark.parametrize("unsafe", ["missing", "symlink", "fifo", "large"])
def test_missing_or_unsafe_readme(project, unsafe):
    path = project / "README.md"
    path.unlink()
    if unsafe == "symlink":
        target = project / "other"
        target.write_text("Do not follow")
        path.symlink_to(target)
    elif unsafe == "fifo":
        os.mkfifo(path)
    elif unsafe == "large":
        path.write_bytes(b"x" * 65537)
    assert result(project)["status"] == "blocked"


def test_operator_denial(project):
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(policy.read_text().replace('effects=["read_fs"]', "effects=[]"))
    assert result(project)["reason"] == "DENIED"


def test_cancellation_before_execution(project):
    cancellation = Event()
    cancellation.set()
    assert result(project, cancellation=cancellation)["status"] == "cancelled"


def test_failed_prerequisite(project, monkeypatch):
    plugin = devkit_example.register()
    prerequisite = CommandSpec(
        "example.environment",
        "Synthetic prerequisite",
        lambda context, arguments: CommandResult(
            "blocked", "Missing fixture", reason="FIXTURE_MISSING"
        ),
    )
    monkeypatch.setattr(
        devkit_example,
        "register",
        lambda: replace(
            plugin,
            commands=(*plugin.commands, prerequisite),
            environment_checks=(CheckSpec("example.environment", prerequisite.id),),
        ),
    )
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    with policy.open("a") as stream:
        stream.write(f'[commands."example.environment"]\nproject={json.dumps(str(project))}\n')
        stream.write('effects=[]\nsurfaces=["python"]\n')
    blocked = result(project)
    assert blocked["reason"] == "PREREQUISITE_FAILED"
    assert blocked["data"]["checks"][0]["result"]["reason"] == "FIXTURE_MISSING"


@pytest.mark.parametrize("broken", ["exception", "output"])
def test_handler_failure_contract(project, monkeypatch, broken):
    plugin = devkit_example.register()

    def handler(context, arguments):
        if broken == "exception":
            raise RuntimeError("Synthetic handler failure")
        return CommandResult("success", "Invalid output", {"lines": "not an integer"})

    command = replace(plugin.commands[0], handler=handler)
    monkeypatch.setattr(devkit_example, "register", lambda: replace(plugin, commands=(command,)))
    assert result(project)["reason"] == (
        "HANDLER_ERROR" if broken == "exception" else "INVALID_OUTPUT"
    )
