import json

import pytest
from devkit.app import create_service
from devkit.contracts import CommandResult, CommandSpec, DevkitError
from devkit.invocation import CommandService
from devkit.policy import load_policy


@pytest.fixture
def profile_policy(tmp_path, monkeypatch):
    config = tmp_path / "config/devkit"
    config.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    projects = [tmp_path / name for name in ("one", "two", "other")]
    for project in projects:
        project.mkdir()
    text = (
        "[profiles.local]\nprojects=" + json.dumps([str(p) for p in projects[:2]]) + "\n"
        '[profiles.local.commands."sample.read"]\neffects=["read_fs"]\nsurfaces=["python","cli"]\n'
    )
    path = config / "policy.toml"
    path.write_text(text)
    path.chmod(0o600)
    return projects, path, text


def command(calls):
    def run(context, arguments):
        calls.append(context.project_root)
        return CommandResult("success", "Read")

    return CommandSpec("sample.read", "Read", run, effects=frozenset({"read_fs"}))


def test_reusable_profile_is_scoped_and_revocable(profile_policy):
    projects, path, _ = profile_policy
    calls = []
    services = [CommandService(create_service(p).settings, (command(calls),)) for p in projects]
    assert [s.execute("sample.read")["result"]["status"] for s in services] == [
        "success",
        "success",
        "blocked",
    ]
    assert calls == projects[:2]
    assert services[0].execute("sample.read", surface="mcp")["result"]["status"] == "blocked"
    path.write_text("")
    assert services[0].execute("sample.read")["result"]["status"] == "blocked"


def test_profile_denial_overrides_other_grants(profile_policy):
    projects, path, text = profile_policy
    text += (
        "\n[profiles.restrict]\nprojects=" + json.dumps([str(projects[0])]) + "\n"
        'deny=["sample.read"]\n[profiles.restrict.commands]\n'
        '[commands."sample.read"]\nproject=' + json.dumps(str(projects[0])) + "\n"
        'effects=["read_fs"]\nsurfaces=["python"]\n'
    )
    path.write_text(text)
    calls = []
    for project, status in zip(projects, ("blocked", "success", "blocked"), strict=True):
        service = CommandService(create_service(project).settings, (command(calls),))
        assert service.execute("sample.read")["result"]["status"] == status
    assert calls == [projects[1]]


def test_profile_grants_are_not_combined_into_broader_privileges(profile_policy):
    projects, path, _ = profile_policy
    path.write_text(
        "\n".join(
            f"[profiles.{name}]\nprojects={json.dumps([str(projects[0])])}\n"
            f'[profiles.{name}.commands."sample.read"]\n'
            f"effects={json.dumps(effects)}\nsurfaces={json.dumps(surfaces)}\n"
            for name, effects, surfaces in [
                ("a", ["read_fs"], ["cli"]),
                ("b", [], ["python"]),
            ]
        )
    )
    calls = []
    service = CommandService(create_service(projects[0]).settings, (command(calls),))
    assert service.execute("sample.read")["result"]["status"] == "blocked"
    assert not calls


def test_repository_cannot_select_or_define_operator_profiles(profile_policy):
    projects, _, _ = profile_policy
    (projects[2] / "devkit.toml").write_text('policy_profiles=["local"]')
    with pytest.raises(DevkitError):
        create_service(projects[2])


def test_relative_and_symlinked_scopes_are_invalid(profile_policy):
    projects, path, _ = profile_policy
    link = projects[0].parent / "alias"
    link.symlink_to(projects[0], target_is_directory=True)
    for scope in ["relative", str(link)]:
        path.write_text(f"[profiles.bad]\nprojects=[{json.dumps(scope)}]\ncommands={{}}")
        with pytest.raises(DevkitError) as caught:
            load_policy(projects[0])
        assert caught.value.reason == "INVALID_POLICY"
