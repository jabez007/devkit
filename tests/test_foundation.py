import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from mccann_hub.devkit.app import create_service
from mccann_hub.devkit.contracts import CommandResult, CommandSpec

from tests.contract_helpers import service_with_grants


@pytest.fixture
def interrupted_command(tmp_path, monkeypatch):
    from mccann_hub.devkit import invocation

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    clock = [1000.0]
    monkeypatch.setattr(invocation, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    settings = create_service(tmp_path).settings

    def execute(outcome, reason):
        def handler(context, arguments):
            if reason == "CANCELLED":
                context.cancellation.set()
            else:
                clock[0] = context.deadline + 1
                if reason == "BOTH":
                    context.cancellation.set()
            return outcome

        command = CommandSpec("test.cleanup", "Clean up an interrupted operation", handler)
        return service_with_grants(settings, (command,)).execute(command.id)

    return execute


@pytest.mark.parametrize("status,reason", [("cancelled", "CANCELLED"), ("error", "TIMEOUT")])
def test_acknowledged_interruption_retains_cleanup_evidence(interrupted_command, status, reason):
    data = {"database": "devkit_owned_fixture", "cleanup": {"status": "removed"}}
    envelope = interrupted_command(CommandResult(status, "Cleanup finished", data, reason), reason)
    assert envelope["result"] == {
        "status": status,
        "summary": "Cleanup finished",
        "data": data,
        "reason": reason,
    }
    saved = json.loads(Path(envelope["evidence_path"]).read_text())
    assert saved["result"] == envelope["result"]


@pytest.mark.parametrize("reason", ["CANCELLED", "TIMEOUT"])
def test_interrupted_success_is_still_refused(interrupted_command, reason):
    envelope = interrupted_command(CommandResult("success", "Ignored interruption"), reason)
    assert envelope["result"]["reason"] == reason
    assert envelope["result"]["status"] != "success"


@pytest.mark.parametrize("status,reason", [("cancelled", "CANCELLED"), ("error", "TIMEOUT")])
def test_interrupted_result_metadata_still_requires_valid_json(interrupted_command, status, reason):
    outcome = CommandResult(status, "Invalid cleanup metadata", {"invalid": object()}, reason)
    assert interrupted_command(outcome, reason)["result"]["reason"] == "INVALID_OUTPUT"


@pytest.mark.parametrize("status,reason", [("cancelled", "CANCELLED"), ("error", "TIMEOUT")])
def test_interrupted_result_metadata_remains_bounded(interrupted_command, status, reason):
    outcome = CommandResult(status, "Oversized cleanup metadata", {"log": "x" * 2_000_000}, reason)
    assert interrupted_command(outcome, reason)["result"]["reason"] == "INVALID_OUTPUT"


def test_expired_deadline_keeps_precedence_over_cancellation(interrupted_command):
    data = {"cleanup": {"status": "removed"}}
    outcome = CommandResult("error", "Deadline cleanup finished", data, "TIMEOUT")
    result = interrupted_command(outcome, "BOTH")["result"]
    assert (result["status"], result["reason"], result["data"]) == ("error", "TIMEOUT", data)


def test_interrupted_result_metadata_is_redacted(interrupted_command, monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "synthetic-cleanup-sensitive-value")
    outcome = CommandResult(
        "cancelled",
        "Cleanup finished",
        {"detail": "synthetic-cleanup-sensitive-value"},
        "CANCELLED",
    )
    envelope = interrupted_command(outcome, "CANCELLED")
    assert envelope["result"]["data"]["detail"] == "[REDACTED]"
    assert "synthetic-cleanup-sensitive-value" not in Path(envelope["evidence_path"]).read_text()


def test_doctor_without_git(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    project = tmp_path / "project"
    project.mkdir()
    result = create_service(project).execute("core.doctor")
    assert result["result"]["status"] == "success"
    from mccann_hub.devkit import __version__

    assert result["producer"]["version"] == __version__
    assert result["producer"]["distribution"] == "mccann-hub-devkit"
    assert result["source"] == {"revision": None, "dirty": None}
    persisted = json.loads(Path(result["evidence_path"]).read_text())
    assert persisted["run_id"] == result["run_id"]
    assert Path(result["evidence_path"]).stat().st_mode & 0o777 == 0o600


def test_invalid_input_does_not_call_handler(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    service = create_service(tmp_path)
    calls = []
    spec = CommandSpec("test.run", "Test", lambda ctx, args: calls.append(1))
    service = service_with_grants(service.settings, (spec,))
    result = service.execute("test.run", {"unexpected": True})
    assert result["result"]["reason"] == "INVALID_INPUT"
    assert not calls


def test_evidence_failure_preserves_observed_outcome(tmp_path, monkeypatch):
    (tmp_path / "state").write_text("not a directory")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    result = create_service(tmp_path).execute("core.doctor")
    assert result["result"]["reason"] == "EVIDENCE_WRITE_FAILED"
    assert result["observed_result"]["status"] == "success"


def test_invalid_output_and_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("TEST_TOKEN", "test-credential-value")
    settings = create_service(tmp_path).settings
    spec = CommandSpec(
        "test.run",
        "Test",
        lambda ctx, args: CommandResult(
            "success",
            "test-credential-value",
            {"password": "hidden"},
        ),
    )
    result = service_with_grants(settings, (spec,)).execute("test.run")
    assert "test-credential-value" not in json.dumps(result)
    assert "hidden" not in json.dumps(result)
    broken = CommandSpec("test.bad", "Bad", lambda ctx, args: None)
    assert service_with_grants(settings, (broken,)).execute("test.bad")["result"]["reason"] == (
        "INVALID_OUTPUT"
    )


def test_plugin_output_cannot_corrupt_protocol(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("TEST_TOKEN", "test-sensitive-value")

    def noisy(context, arguments):
        print("test-sensitive-value")
        return CommandResult("success", "Done")

    spec = CommandSpec("test.noisy", "Noisy", noisy)
    result = service_with_grants(create_service(tmp_path).settings, (spec,)).execute(spec.id)
    assert capsys.readouterr().out == ""
    assert result["diagnostics"] == "[REDACTED]\n"


def test_non_json_input_returns_error_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    result = create_service(tmp_path).execute("core.doctor", {"invalid": b"bytes"})
    assert result["result"]["reason"] == "INVALID_INPUT"


@pytest.mark.parametrize("data", [{1: "value"}, {"value": (1, 2)}])
def test_non_json_output_is_normalized_to_error(tmp_path, monkeypatch, data):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    command = CommandSpec(
        "test.output", "Output", lambda ctx, args: CommandResult("success", "OK", data)
    )
    result = service_with_grants(create_service(tmp_path).settings, (command,)).execute(command.id)
    assert result["result"]["reason"] == "INVALID_OUTPUT"


def test_source_metadata_does_not_execute_repository_hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("init")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "Fixture",
    )
    hook = root / "monitor.sh"
    hook.write_text('#!/bin/sh\ntouch "$PWD/hook-ran"\n')
    hook.chmod(0o700)
    git("config", "core.fsmonitor", str(hook))
    result = create_service(root).execute("core.doctor")
    assert result["result"]["status"] == "success"
    assert result["source"]["revision"]
    assert result["source"]["dirty"] is True
    assert not (root / "hook-ran").exists()


def test_handler_receives_resolved_evidence_location(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    settings = create_service(tmp_path).settings
    command = CommandSpec(
        "test.location",
        "Inspect location",
        lambda ctx, args: CommandResult("success", "Resolved", {"state": str(ctx.state_root)}),
    )
    result = service_with_grants(settings, (command,)).execute(command.id)
    assert result["result"]["data"]["state"] == str(settings.state_root)
