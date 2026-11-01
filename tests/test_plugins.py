import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from mccann_hub.devkit.app import create_service
from mccann_hub.devkit.contracts import CommandResult, CommandSpec, DevkitError, Specialization
from mccann_hub.devkit.discovery import Candidate, activate
from mccann_hub.devkit.invocation import CommandService
from mccann_hub.devkit.policy import Policy


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

    return Candidate("sample", "mccann-hub-devkit-sample", "0.1.0", SimpleNamespace(load=load))


def test_disabled_and_untrusted_plugins_are_not_loaded():
    calls = []
    entry = candidate(calls)
    assert activate((), Policy(), (entry,)) == ()
    with pytest.raises(DevkitError, match="not trusted"):
        activate(("sample",), Policy(), (entry,))
    assert not calls


def test_duplicate_missing_and_incompatible_plugins():
    entry = candidate([], Specialization("sample", (), api_version="99"))
    trusted = Policy({"mccann-hub-devkit-sample": "0.1.0"})
    for candidates in [(), (entry, entry)]:
        with pytest.raises(DevkitError, match="exactly one"):
            activate(("sample",), trusted, candidates)
    with pytest.raises(DevkitError, match="Cannot activate"):
        activate(("sample",), trusted, (entry,))


def test_old_distribution_trust_does_not_authorize_renamed_plugin():
    calls = []
    with pytest.raises(DevkitError, match="trust"):
        activate(("sample",), Policy({"devkit-sample": "0.1.0"}), (candidate(calls),))
    assert not calls


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
        activate(("sample",), Policy({"mccann-hub-devkit-sample": "0.1.0"}), (entry,))


def test_registration_output_is_rejected_without_leaking(capsys):
    def noisy():
        print("plugin registration output")
        return Specialization("sample", ())

    entry = Candidate(
        "sample", "mccann-hub-devkit-sample", "0.1.0", SimpleNamespace(load=lambda: noisy)
    )
    with pytest.raises(DevkitError, match="Cannot activate"):
        activate(("sample",), Policy({"mccann-hub-devkit-sample": "0.1.0"}), (entry,))
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "not_namespaced"},
        {"id": "other.run"},
        {"surfaces": frozenset({"unknown"})},
        {"output_schema": {"type": "array"}},
    ],
)
def test_invalid_command_declarations_fail_activation(changes):
    spec = CommandSpec("sample.run", "Sample", lambda ctx, args: CommandResult("success", "OK"))
    entry = candidate([], Specialization("sample", (replace(spec, **changes),)))
    with pytest.raises(DevkitError, match="Cannot activate"):
        activate(("sample",), Policy({"mccann-hub-devkit-sample": "0.1.0"}), (entry,))
