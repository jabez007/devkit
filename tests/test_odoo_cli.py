import json
import subprocess
import sys
from pathlib import Path

import pytest

CASES = json.loads(Path("tests/fixtures/odoo/cases.json").read_text())


@pytest.mark.parametrize(
    "index", range(len(CASES)), ids=[f"{case['fixture']}-{case['status']}" for case in CASES]
)
def test_representative_cli_and_evidence(index):
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_odoo_fixtures.py",
            str(Path(".venv/bin/devkit").resolve()),
            str(index),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
