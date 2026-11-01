"""Acceptance for the shipped CI recipe, using real independently installed wheels."""

import hashlib
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from check_odoo_fixtures import invoke

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/ci"
VARIANTS = {
    "passing": None,
    "go-failure": ("total.go", "return result", "return result + 1"),
    "odoo-blocked": ("devkit.toml", "strict_dependencies = false", "strict_dependencies = true"),
    "invalid-profile": ("devkit.toml", '"go.tests", "odoo.manifests"', '"missing.check"'),
}


def _prepare(binary, wheels, root, env, variant):
    project = root / "project with spaces"
    shutil.copytree(EXAMPLE / "project", project)
    env = {
        **env,
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_STATE_HOME": str(root / "reports/state"),
        "DEVKIT_BIN": str(binary),
        "DEVKIT_PROJECT": str(project),
        "DEVKIT_REPORTS": str(root / "reports"),
    }
    subprocess.run(
        [sys.executable, str(EXAMPLE / "prepare_policy.py"), str(project), str(wheels)],
        env=env,
        check=True,
    )
    assert (root / "config/devkit/policy.toml").stat().st_mode & 0o777 == 0o600
    if replacement := VARIANTS[variant]:
        name, old, new = replacement
        path = project / name
        assert old in path.read_text()
        path.write_text(path.read_text().replace(old, new))
    return project, env


def _execute(env, expected):
    completed = subprocess.run(
        ["bash", str(EXAMPLE / "check.sh")], env=env, text=True, capture_output=True, timeout=120
    )
    assert completed.returncode == expected, completed.stdout + completed.stderr
    reports = Path(env["DEVKIT_REPORTS"])
    return json.loads((reports / "check.json").read_text())


def _evidence(binary, wheels, project, root, env, envelope):
    reports = root / "reports"
    run_id = envelope["run_id"]
    assert (reports / "run-id.txt").read_text().strip() == run_id
    saved = json.loads(Path(envelope["evidence_path"]).read_text())
    shown = json.loads((reports / "shown.json").read_text())["result"]["data"]
    assert shown["run"] == saved
    assert shown["references"] == ["ci:artifact"]
    assert json.loads((reports / "prune-preview.json").read_text())["result"]["data"]["dry_run"]
    family = {run_id}
    versions = {"go.test": ("go", "0.1.0"), "odoo.module.validate": ("odoo", "0.5.0")}
    for child in saved["result"]["data"].get("checks", []):
        family.add(child["run_id"])
        record = invoke(binary, project, env, "runs", "show", child["run_id"])["result"]["data"][
            "run"
        ]
        assert record["parent_run_id"] == run_id
        assert record["result"] == child["result"]
        name, version = versions[record["command"]]
        wheel = wheels / f"mccann_hub_devkit_{name}-{version}-py3-none-any.whl"
        assert (
            record["producer"]["artifact_sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
        )
    _relocate(binary, root, reports, saved, env)
    _retention(binary, project, env, family, run_id)


def _relocate(binary, root, reports, saved, env):
    # A downloaded artifact has a different absolute path and no operator policy.
    restored = root / "download"
    shutil.copytree(reports, restored)
    relocated = {
        **env,
        "XDG_STATE_HOME": str(restored / "state"),
        "XDG_CONFIG_HOME": str(root / "no-policy"),
    }
    shown = invoke(binary, root, relocated, "runs", "show", saved["run_id"], "--all-projects")
    assert shown["result"]["data"]["run"] == saved
    assert not list(restored.rglob("*.toml"))
    assert not list(restored.rglob("*.whl"))


def _retention(binary, project, env, family, run_id):
    pruning = ("runs", "prune", "--older-than-days", "0", "--keep-last", "0", "--apply")
    result = invoke(binary, project, env, *pruning)["result"]["data"]
    assert not family.intersection(result["deleted"])
    remaining = invoke(binary, project, env, "runs", "list")["result"]["data"]["runs"]
    assert {item["run_id"] for item in remaining} == family
    invoke(binary, project, env, "runs", "unpin", run_id, "--reference", "ci:artifact")
    assert set(invoke(binary, project, env, *pruning)["result"]["data"]["deleted"]) == family


def _maintenance_failure(binary, wheels, root, env, variant, expected):
    _, env = _prepare(binary, wheels, root, env, variant)
    wrapper = root / "broken-evidence"
    wrapper.write_text(
        '#!/usr/bin/env bash\nif [[ "${4:-}" == runs && "${5:-}" == pin ]]; then exit 1; fi\n'
        f'exec {shlex.quote(str(binary))} "$@"\n'
    )
    wrapper.chmod(0o700)
    envelope = _execute({**env, "DEVKIT_BIN": str(wrapper)}, expected)
    assert envelope["result"]["status"] == ("success" if variant == "passing" else "blocked")


def exercise(binary, wheels, root, env):
    expected = {"passing": 0, "go-failure": 1, "odoo-blocked": 2, "invalid-profile": 3}
    statuses = {0: "success", 1: "failed", 2: "blocked", 3: "error"}
    for variant, code in expected.items():
        case = root / variant
        project, case_env = _prepare(binary, wheels, case, env, variant)
        envelope = _execute(case_env, code)
        assert envelope["result"]["status"] == statuses[code]
        assert int((case / "reports/check-exit-code.txt").read_text()) == code
        _evidence(binary, wheels, project, case, case_env, envelope)
    _maintenance_failure(binary, wheels, root / "export-failure", env, "passing", 3)
    _maintenance_failure(binary, wheels, root / "export-blocked", env, "odoo-blocked", 2)
    _, case_env = _prepare(binary, wheels, root / "doctor-failure", env, "passing")
    Path(case_env["XDG_CONFIG_HOME"], "devkit/policy.toml").write_text("")
    completed = subprocess.run(
        ["bash", str(EXAMPLE / "check.sh")], env=case_env, capture_output=True
    )
    assert completed.returncode == 2
    reports = Path(case_env["DEVKIT_REPORTS"])
    assert not (reports / "check.json").exists()
    assert (
        json.loads((reports / "doctor.json").read_text())["result"]["reason"] == "UNTRUSTED_PLUGIN"
    )
    print(
        "PASS: CI recipe, seven scenarios, pinned wheel identity, relocated evidence and retention"
    )
