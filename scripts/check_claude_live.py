"""Opt-in native Claude qualification, using disposable real Go/Odoo/Beads projects.

Arguments: temporary-root wheels-directory constraints-file claude-executable.
Requires DEVKIT_BEADS_BINARY, an authenticated API environment, and native Claude.
Never called by CI or plugin installation. No personal Claude settings are loaded.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from check_beads_lifecycle import grant, invoke
from check_beads_wheels import bd, setup
from check_claude_workflow import inspect_run
from check_wheels import ROOT, cli, run


def prepare(root, wheels, constraints, domain, binary):
    project, env, _, _ = setup(root, wheels, constraints, domain, binary)
    grant(root, project)
    created = invoke(
        root,
        project,
        env,
        "create",
        {
            "title": f"Native Claude {domain} qualification",
            "description": "Disposable verification exercise, not production work",
        },
    )
    reference = created["result"]["data"]["item"]["ref"]
    if domain == "go":
        (project / "quantity.go").write_text(
            "package demo\nfunc Remaining(a, b int) int { return a + b }\n"
        )
        (project / "quantity_test.go").write_text(
            'package demo\nimport "testing"\nfunc TestRemaining(t *testing.T) { '
            'if Remaining(10, 3) != 7 { t.Fatal("expected 7 remaining") } }\n'
        )
    bundle = root / "plugin"
    shutil.copytree(ROOT / "integrations/claude-code", bundle)
    env["CLAUDE_CONFIG_DIR"] = str(root / "claude-config")
    Path(env["CLAUDE_CONFIG_DIR"]).mkdir()
    # Skills can find the reviewed executable without relying on repository PATH entries.
    env["PATH"] = f"{root / 'venv/bin'}:{env['PATH']}"
    return project, env, reference, bundle


def prompt(project, reference, root, bundle, domain):
    task = (
        "Run check verify BEFORE editing to capture a failing run. Inspect quantity.go and "
        "quantity_test.go, fix only the addition bug in quantity.go, then check verify again "
        "to capture a passing run. Associate BOTH runs with the selected item."
        if domain == "go"
        else "Do not edit the addon. Run check verify, then run odoo.module.validate with "
        '{"strict_dependencies":true}. Explain the ordinary success and strict blocked '
        "result, including unknown dependencies and missing runtime coverage. Associate BOTH runs."
    )
    return (
        "Use the mccann-hub-devkit:devkit-work-items and devkit-verification plugin skills. "
        f"This is an authorized disposable exercise in {project}. The explicitly selected item "
        f"is {reference}. Inspect ready items, that item's description and dependencies. "
        "I authorize claiming only this item as actor claude-code/acceptance, the specified "
        "verification and code change, and the two evidence associations. "
        f"{task} Retrieve both persisted results, repeat one association to check idempotency, "
        "and inspect final work-item state. Leave it in_progress; do not comment or close. "
        "Never initialize a ledger, alter policy, install packages, run git mutations, or use "
        "network tools. Do not inspect environment variables or credentials. "
        f"Use {root / 'venv/bin/devkit'} for every Devkit command, and "
        f"{root / 'venv/bin/python'} {bundle / 'scripts/checkout.py'} for root resolution. "
        "No other shell executables are authorized. File reads are allowed for the plugin "
        "instructions, this disposable project, its operator policy and evidence. "
        "Use the Edit tool for the Go fix. Summarize actual statuses, run IDs, selected "
        "project, task state, and remaining coverage. If a tool is denied or fails, report it."
    )


def session(claude, root, project, env, bundle, text):
    arguments = [
        str(claude),
        "--bare",
        "--no-session-persistence",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--plugin-dir",
        str(bundle),
        "--add-dir",
        str(root),
        "--tools",
        "Bash,Read,Edit,Skill",
        "--allowedTools",
        f"Bash({root / 'venv/bin/devkit'} *)",
        f"Bash({root / 'venv/bin/python'} {bundle / 'scripts/checkout.py'}*)",
        "Read",
        "Edit",
        "Skill",
        "--permission-prompts",
        "none",
        "--max-budget-usd",
        "5",
        "--output-format",
        "json",
        "--print",
        text,
    ]
    result = subprocess.run(
        arguments, cwd=project, env=env, capture_output=True, text=True, timeout=600
    )
    (root / "claude-result.json").write_text(result.stdout)
    (root / "claude-stderr.txt").write_text(result.stderr)
    report = json.loads(result.stdout)
    assert result.returncode == 0, (
        f"Claude exited {result.returncode}: {report.get('result', report.get('subtype'))}; "
        f"see {root}"
    )
    assert not report.get("is_error"), report.get("result", report.get("subtype"))
    assert not report.get("permission_denials"), report.get("permission_denials")
    return report


def verify(root, project, env, reference, domain, binary):
    state = cli(
        root, project, env, "run", "beads.item.show", "--args", json.dumps({"ref": reference})
    )
    item = state["result"]["data"]["item"]
    assert item["status"] == "in_progress", item
    assert item["assignee"] == "claude-code/acceptance", item
    records = []
    for path in (root / "state/devkit/runs").glob("*/result.json"):
        envelope = json.loads(path.read_text())
        if envelope["command"] in {"core.check", "odoo.module.validate"}:
            shown = cli(root, project, env, "runs", "show", envelope["run_id"])["result"]["data"]
            if reference in shown["references"]:
                assert shown["references"] == [reference]
                records.append(envelope)
    statuses = {record["result"]["status"] for record in records}
    assert statuses == ({"failed", "success"} if domain == "go" else {"success", "blocked"}), (
        statuses
    )
    assert bd(binary, project, env, "comments", reference.rsplit(":", 1)[1], "--json") == []
    shutil.rmtree(root / "plugin")
    for envelope in records:
        evidence = root / "state/devkit/runs" / envelope["run_id"] / "result.json"
        inspect_run(root, project, env, {**envelope, "evidence_path": str(evidence)})
    return [
        {"run_id": record["run_id"], "status": record["result"]["status"]} for record in records
    ]


def main():
    root, wheels, constraints, claude = map(lambda value: Path(value).resolve(), sys.argv[1:])
    binary = Path(os.environ["DEVKIT_BEADS_BINARY"]).resolve()
    for domain in ("go", "odoo"):
        target = root / domain
        target.mkdir(parents=True)
        project, env, reference, bundle = prepare(target, wheels, constraints, domain, binary)
        run(str(claude), "plugin", "validate", "--strict", str(bundle), env=env, cwd=project)
        report = session(
            claude, target, project, env, bundle, prompt(project, reference, target, bundle, domain)
        )
        evidence = verify(target, project, env, reference, domain, binary)
        summary = {"reference": reference, "evidence": evidence, "result": report["result"]}
        (target / "qualification.json").write_text(json.dumps(summary, indent=2))
        print(f"PASS: native Claude {domain}, selected task, actual evidence, plugin removal")


if __name__ == "__main__":
    main()
