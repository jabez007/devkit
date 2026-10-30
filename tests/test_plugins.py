import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from devkit.app import create_service
from devkit.contracts import CommandResult, CommandSpec, DevkitError, Specialization
from devkit.discovery import Candidate, activate
from devkit.invocation import CommandService
from devkit.policy import Policy


def candidate(marker, plugin=None):
    def load():
        marker.append("imported")
        return lambda: plugin or Specialization(
            "sample",
            (
                CommandSpec(
                    "sample.run", "Sample", lambda ctx, args: CommandResult("success", "OK")
                ),
            ),
        )

    return Candidate("sample", "devkit-sample", "0.1.0", SimpleNamespace(load=load))


def test_disabled_and_untrusted_plugins_are_not_loaded():
    calls = []
    entry = candidate(calls)
    assert activate((), Policy(), (entry,)) == ()
    with pytest.raises(DevkitError, match="not trusted"):
        activate(("sample",), Policy(), (entry,))
    assert not calls


def test_duplicate_missing_and_incompatible_plugins():
    entry = candidate([], Specialization("sample", (), api_version="99"))
    trusted = Policy({"devkit-sample": "0.1.0"})
    for candidates in [(), (entry, entry)]:
        with pytest.raises(DevkitError, match="exactly one"):
            activate(("sample",), trusted, candidates)
    with pytest.raises(DevkitError, match="Cannot activate"):
        activate(("sample",), trusted, (entry,))


def test_denied_command_never_reaches_handler(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    calls = []
    spec = CommandSpec(
        "sample.run", "Sample", lambda ctx, args: calls.append(1), effects=frozenset({"write_fs"})
    )
    service = CommandService(create_service(tmp_path).settings, (spec,))
    assert service.execute(spec.id)["result"]["status"] == "blocked"
    assert not calls
    with pytest.raises(DevkitError, match="Duplicate"):
        CommandService(service.settings, (spec, spec))
    with pytest.raises(DevkitError):
        CommandService(service.settings, (replace(spec, effects=frozenset({"magic"})),))


def test_repository_cannot_grant_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "devkit.toml").write_text('[commands."sample.run"]\neffects=["write_fs"]')
    with pytest.raises(DevkitError, match="Invalid settings"):
        create_service(tmp_path)


def test_policy_revocation_applies_to_existing_service(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    config = tmp_path / "config/devkit"
    config.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    spec = CommandSpec("sample.run", "Sample", lambda ctx, args: CommandResult("success", "OK"))
    service = CommandService(create_service(root).settings, (spec,))
    (config / "policy.toml").write_text(
        f'[commands."sample.run"]\nproject={json.dumps(str(root))}\neffects=[]\nsurfaces=["python"]'
    )
    (config / "policy.toml").chmod(0o600)
    assert service.execute(spec.id)["result"]["status"] == "success"
    (config / "policy.toml").write_text('deny=["sample.run"]')
    assert service.execute(spec.id)["result"]["status"] == "blocked"


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array"},
        {"type": "object", "$ref": "https://example.invalid/schema"},
        {"type": "object", "$schema": "http://json-schema.org/draft-07/schema#"},
    ],
)
def test_incompatible_schemas_fail_activation(schema):
    command = CommandSpec(
        "sample.run",
        "Sample",
        lambda ctx, args: CommandResult("success", "OK"),
        input_schema=schema,
    )
    entry = candidate([], Specialization("sample", (command,)))
    with pytest.raises(DevkitError, match="Cannot activate"):
        activate(("sample",), Policy({"devkit-sample": "0.1.0"}), (entry,))


def test_registration_output_is_rejected_without_leaking(capsys):
    def noisy():
        print("plugin registration output")
        return Specialization("sample", ())

    entry = Candidate("sample", "devkit-sample", "0.1.0", SimpleNamespace(load=lambda: noisy))
    with pytest.raises(DevkitError, match="Cannot activate"):
        activate(("sample",), Policy({"devkit-sample": "0.1.0"}), (entry,))
    assert capsys.readouterr().out == ""
