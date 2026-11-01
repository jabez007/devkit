import json
import os
import subprocess
from pathlib import Path


def cli(project, *args):
    return subprocess.run(
        [str(Path(".venv/bin/devkit").resolve()), "--project", str(project), "--json", *args],
        text=True,
        capture_output=True,
        timeout=10,
    )


def test_doctor_explains_its_scope(odoo_project):
    project, _ = odoo_project
    completed = cli(project, "doctor")
    assert completed.returncode == 0
    result = json.loads(completed.stdout)["result"]
    assert "Project checks have not run" in result["summary"]
    assert "project validation" in result["data"]["not_checked"]


def test_doctor_explains_untrusted_plugin(odoo_project):
    project, _ = odoo_project
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text("")
    completed = cli(project, "doctor")
    assert completed.returncode == 2
    result = json.loads(completed.stdout)["result"]
    assert result["reason"] == "UNTRUSTED_PLUGIN"
    assert "odoo" in result["summary"]
    assert "policy.toml" in result["summary"]


def test_invalid_configuration_names_the_file(odoo_project):
    project, _ = odoo_project
    (project / "devkit.toml").write_text("plugins = 42")
    completed = cli(project, "doctor")
    assert completed.returncode == 3
    result = json.loads(completed.stdout)["result"]
    assert result["reason"] == "INVALID_CONFIG"
    assert "devkit.toml" in result["summary"]


def test_malformed_cli_arguments_are_input_errors(odoo_project):
    project, _ = odoo_project
    completed = cli(project, "run", "odoo.module.validate", "--args", "{broken")
    assert completed.returncode == 3
    result = json.loads(completed.stdout)["result"]
    assert result["reason"] == "INVALID_INPUT"
    assert "--args" in result["summary"]


def test_plugin_details_distinguish_selection_and_trust(odoo_project):
    project, _ = odoo_project
    result = cli(project, "plugins", "list", "--details")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)["result"]["data"]
    rows = {row["id"]: row for row in data["plugins"]}
    assert rows["odoo"]["selected"] is True
    assert rows["odoo"]["trust"] == "version-trust-configured"
    assert rows["beads"]["selected"] is False
    assert rows["beads"]["trust"] == "not-configured"
    assert data["activation"] == "not-attempted"
    assert data["artifact_verification"] == "not-performed"
    assert data["policy_file"].endswith("policy.toml")


def test_plugin_list_still_works_with_broken_settings(odoo_project):
    project, _ = odoo_project
    (project / "devkit.toml").write_text("invalid syntax")
    assert cli(project, "plugins").returncode == 0
    details = cli(project, "plugins", "list", "--details")
    assert json.loads(details.stdout)["result"]["reason"] == "INVALID_CONFIG"


def test_plugin_details_do_not_verify_configured_pin(odoo_project):
    project, _ = odoo_project
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(
        '[trusted_plugins.devkit-odoo]\nversion="0.5.0"\n'
        'wheel="/nonexistent/reviewed.whl"\nsha256="' + "0" * 64 + '"\n'
    )
    completed = cli(project, "plugins", "list", "--details")
    assert completed.returncode == 0
    data = json.loads(completed.stdout)["result"]["data"]
    odoo = next(row for row in data["plugins"] if row["id"] == "odoo")
    assert odoo["trust"] == "wheel-pin-unverified"
    assert data["artifact_verification"] == "not-performed"


def test_plugin_details_report_missing_selection_and_version_mismatch(odoo_project):
    project, _ = odoo_project
    (project / "devkit.toml").write_text('plugins=["odoo", "absent"]\n')
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text('[trusted_plugins]\ndevkit-odoo="0.0.0"\n')
    completed = cli(project, "plugins", "list", "--details")
    assert completed.returncode == 0
    data = json.loads(completed.stdout)["result"]["data"]
    assert data["missing"] == ["absent"]
    odoo = next(row for row in data["plugins"] if row["id"] == "odoo")
    assert odoo["trust"] == "version-mismatch"


def test_plugin_validation_uses_doctor_diagnostics(odoo_project):
    project, _ = odoo_project
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text("")
    completed = cli(project, "plugins", "validate")
    assert completed.returncode == 2
    result = json.loads(completed.stdout)["result"]
    assert result["reason"] == "UNTRUSTED_PLUGIN"
    assert "policy.toml" in result["summary"]
