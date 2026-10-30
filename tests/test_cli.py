import json
import os
import subprocess
from pathlib import Path


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
