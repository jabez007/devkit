from dataclasses import replace

from mccann_hub.devkit.app import create_service
from mccann_hub.devkit.contracts import CheckSpec, CommandResult, CommandSpec
from mccann_hub.devkit.invocation import CommandService
from mccann_hub.devkit.policy import Policy


def test_profiles_and_prerequisites_share_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    settings = replace(
        create_service(tmp_path).settings,
        profiles={
            "quick": ["sample.check"],
            "empty": [],
            "missing": ["missing.check"],
        },
    )
    calls = []

    def work(context, arguments):
        calls.append("work")
        return CommandResult("success", "Done")

    commands = (
        CommandSpec("sample.work", "Work", work),
        CommandSpec(
            "sample.environment",
            "Environment",
            lambda ctx, args: CommandResult("failed", "Unavailable"),
        ),
    )
    grant = {"project": str(tmp_path), "effects": [], "surfaces": ["python"]}
    policy = Policy(commands={spec.id: grant for spec in commands})
    service = CommandService(
        settings,
        commands,
        policy,
        checks=(CheckSpec("sample.check", "sample.work"),),
        prerequisites={"sample.work": (CheckSpec("sample.env", "sample.environment"),)},
    )
    result = service.execute("core.check", {"profile": "quick"})
    assert result["result"]["status"] == "blocked"
    assert not calls
    assert result["result"]["data"]["checks"][0]["result"]["reason"] == "PREREQUISITE_FAILED"
    assert service.execute("core.check", {"profile": "empty"})["result"]["reason"] == "NO_CHECKS"
    assert (
        service.execute("core.check", {"profile": "missing"})["result"]["reason"]
        == "INVALID_PROFILE"
    )


def test_profile_success_has_child_evidence(odoo_project):
    project, _ = odoo_project
    with (project / "devkit.toml").open("a") as stream:
        stream.write('\n[profiles]\nstatic=["odoo.manifests"]\n')
    result = create_service(project).execute("core.check", {"profile": "static"})
    assert result["result"]["status"] == "success"
    assert result["result"]["data"]["checks"][0]["evidence_path"]
