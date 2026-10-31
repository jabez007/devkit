"""Exercise synthetic repositories through any installed devkit CLI and its evidence store."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/odoo"
EXIT_CODES = {"success": 0, "failed": 1, "blocked": 2, "error": 3}


def invoke(binary, project, env, *args, expected=0, structured=True):
    command = [str(binary), "--project", str(project)]
    if structured:
        command.append("--json")
    completed = subprocess.run(
        [*command, *args], cwd=project, env=env, text=True, capture_output=True, timeout=30
    )
    assert completed.returncode == expected, completed.stdout + completed.stderr
    return json.loads(completed.stdout) if structured else completed.stdout


def exercise_case(binary, root, case):
    project = root / "project"
    shutil.copytree(FIXTURES / case["fixture"], project)
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_STATE_HOME": str(root / "state"),
    }
    env.pop("PYTHONPATH", None)
    plugins = invoke(binary, project, env, "plugins")["result"]["data"]["plugins"]
    version = next(plugin["version"] for plugin in plugins if plugin["id"] == "odoo")
    policy = root / "config/devkit/policy.toml"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        f'[trusted_plugins]\ndevkit-odoo="{version}"\n'
        '[commands."odoo.module.validate"]\n'
        f'project={json.dumps(str(project))}\neffects=["read_fs"]\nsurfaces=["cli"]\n'
    )
    policy.chmod(0o600)
    args = ("run", "odoo.module.validate", "--args", json.dumps(case["arguments"]))
    expected = EXIT_CODES[case["status"]]
    envelope = invoke(binary, project, env, *args, expected=expected)
    result = envelope["result"]
    assert (result["status"], result["reason"]) == (case["status"], case["reason"]), result
    counts = result["data"]["dependency_counts"]
    assert [counts[name] for name in ("resolved", "missing", "unknown", "invalid")] == case[
        "counts"
    ], result
    saved = json.loads(Path(envelope["evidence_path"]).read_text())
    assert saved["result"] == result
    shown = invoke(binary, project, env, "runs", "show", envelope["run_id"])
    assert shown["result"]["data"]["run"] == saved
    text = invoke(binary, project, env, *args, expected=expected, structured=False)
    assert result["summary"] in text
    assert "Evidence:" in text
    assert not (project / "manifest-executed").exists()
    assert not (project / "xml-executed").exists()
    assert not (project / "csv-executed").exists()
    _assert_domain_details(case, result["data"])
    return envelope


def _assert_domain_details(case, data):
    for key in (
        "xml_counts",
        "xml_reference_counts",
        "csv_counts",
        "csv_reference_counts",
        "dependency_graph",
    ):
        if key in case:
            assert data[key] == case[key], data
    for kind in ("xml", "csv"):
        key = "reference_reasons" if kind == "xml" else "csv_reference_reasons"
        if key in case:
            reasons = [
                ref["reason"]
                for module in data["modules"]
                for file in module[kind]["files"]
                for ref in file["references"]
                if ref["status"] == "unknown"
            ]
            assert reasons == case[key], reasons
    if case["fixture"] == "optional":
        external = data["modules"][0]["external_dependencies"]
        assert {edge["kind"] for edge in external} == {"python", "bin"}
        assert all(edge["status"] == "unknown" for edge in external)
    if case["fixture"] == "oca":
        module = next(item for item in data["modules"] if item["module"] == "acme_audit")
        assert module["dependencies"][0]["path"] == "vendor/server-tools/auditlog"
    if case["reason"] in {"INVALID_ADDONS", "MISSING_ADDONS"}:
        assert not data["inventory"]["scan_complete"]
        assert not data["inspection_complete"]
    else:
        assert data["inspection_complete"]
        assert data["inventory"]["scan_complete"]
        assert "runtime" in data["not_checked"]


def main(binary, selected=None):
    cases = json.loads((FIXTURES / "cases.json").read_text())
    if selected is not None:
        cases = [cases[int(selected)]]
    with tempfile.TemporaryDirectory(prefix="devkit-odoo-fixtures-") as temporary:
        for index, case in enumerate(cases):
            exercise_case(Path(binary).resolve(), Path(temporary) / str(index), case)
    print(f"PASS: {len(cases)} Odoo CLI cases, persisted evidence, retrieval and text diagnostics")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
