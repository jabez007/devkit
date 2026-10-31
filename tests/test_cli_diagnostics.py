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
