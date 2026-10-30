import json
from pathlib import Path

from devkit.app import create_service
from devkit.contracts import CommandResult, CommandSpec
from devkit.invocation import CommandService
from devkit.policy import Policy


def service_with_grants(settings, commands):
    grants = {
        spec.id: {
            "project": str(settings.project_root),
            "effects": list(spec.effects),
            "surfaces": ["python"],
        }
        for spec in commands
    }
    return CommandService(settings, commands, Policy(commands=grants))


def test_doctor_without_git(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    project = tmp_path / "project"
    project.mkdir()
    result = create_service(project).execute("core.doctor")
    assert result["result"]["status"] == "success"
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
