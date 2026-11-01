import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.beads_helpers import configure


def test_cli_configuration_errors_are_json(tmp_path):
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    executable = str(Path(".venv/bin/devkit").resolve())
    for content in ["unknown = true", 'timeout = "invalid"', "not toml"]:
        (tmp_path / "devkit.toml").write_text(content)
        proc = subprocess.run(
            [executable, "--project", str(tmp_path), "--json", "doctor"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 3
        assert json.loads(proc.stdout)["result"]["reason"] == "INVALID_CONFIG"
        assert "Traceback" not in proc.stderr


def test_text_discovery_lists_identifiers(tmp_path):
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    executable = str(Path(".venv/bin/devkit").resolve())
    for action, identifiers in [
        ("plugins", ["go (mccann-hub-devkit-go 0.1.0)", "odoo (mccann-hub-devkit-odoo 0.5.0)"]),
        ("commands", ["core.doctor", "core.check"]),
    ]:
        proc = subprocess.run(
            [executable, "--project", str(tmp_path), action],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert all(identifier in proc.stdout for identifier in identifiers)


@pytest.mark.parametrize("action", [("doctor",), ("check", "verify")])
def test_text_aggregates_explain_failed_prerequisites(beads_project, action):
    configure(beads_project, context={"is_worktree": True})
    (beads_project / "devkit.toml").write_text(
        'plugins=["beads"]\n[profiles]\nverify=["beads.workspace"]\n'
    )
    executable = str(Path(".venv/bin/devkit").resolve())
    args = [executable, "--project", str(beads_project)]
    structured = subprocess.run([*args, "--json", *action], capture_output=True, text=True)
    assert structured.returncode == 2
    envelope = json.loads(structured.stdout)
    child = envelope["result"]["data"]["checks"][0]
    plain = subprocess.run([*args, *action], capture_output=True, text=True)
    assert plain.returncode == 2
    assert child["check"] in plain.stdout
    assert child["result"]["reason"] in plain.stdout
    assert child["result"]["summary"] in plain.stdout
    assert "runs show" in plain.stdout
    assert f"--project {beads_project}" in plain.stdout
    # Text rendering must leave the persisted machine result intact.
    evidence = Path(plain.stdout.split("Evidence: ")[-1].strip())
    stored = json.loads(evidence.read_text())
    assert stored["result"]["data"]["checks"][0]["result"] == child["result"]
