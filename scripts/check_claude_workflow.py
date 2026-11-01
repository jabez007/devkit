"""Exercise the copied Claude bundle with independent wheels, without a model.

Arguments: temporary-root wheels-directory constraints-file.
Native model qualification is separate: check_claude_live.py.
"""

import json
import shutil
import sys
from pathlib import Path

from check_wheels import ROOT, absent, cli, install, policy, run


def selected(bundle, project, env):
    nested = project / "nested directory"
    nested.mkdir(exist_ok=True)
    result = run(
        sys.executable,
        str(bundle / "scripts/checkout.py"),
        cwd=nested,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == str(project)
    return Path(result.stdout.strip())


def inspect_run(root, project, env, envelope):
    shown = cli(root, project, env, "runs", "show", envelope["run_id"])
    assert shown["result"]["data"]["run"]["result"] == envelope["result"]
    assert json.loads(Path(envelope["evidence_path"]).read_text())["result"] == envelope["result"]


def exercise(root, wheels, constraints, domain):
    project, env = install(
        root,
        wheels,
        ["mccann_hub.devkit", f"mccann_hub.devkit_{domain}"],
        constraints,
    )
    absent(root, project, env, ["mcp", "odoo", "mccann_hub.devkit_beads"])
    assert not (root / "venv/bin/devkit-mcp").exists()
    bundle = root / "copied plugin"
    shutil.copytree(ROOT / "integrations/claude-code", bundle)
    run("git", "init", "-q", str(project))
    project = selected(bundle, project, env)
    check = "go.tests" if domain == "go" else "odoo.manifests"
    (project / "devkit.toml").write_text(
        f'plugins=["{domain}"]\ntimeout=90\n[profiles]\nverify=["{check}"]\n'
    )
    discovered = cli(root, project, env, "plugins", "list", "--details")
    assert discovered["result"]["data"]["activation"] == "not-attempted"
    assert (
        cli(root, project, env, "plugins", "validate", expected=2)["result"]["reason"]
        == "UNTRUSTED_PLUGIN"
    )
    command = "go.test" if domain == "go" else "odoo.module.validate"
    effects = ["read_fs", "write_fs", "execute_process", "network_read", "network_write"]
    policy(root, project, [domain], {command: effects if domain == "go" else ["read_fs"]})
    cli(root, project, env, "plugins", "validate")
    assert command in cli(root, project, env, "commands")["result"]["data"]["commands"]
    results = go_checks(root, project, env) if domain == "go" else odoo_checks(root, project, env)
    for envelope in results:
        inspect_run(root, project, env, envelope)
    # The plugin is instruction files, not a prerequisite of the CLI/evidence store.
    shutil.rmtree(bundle)
    for envelope in results:
        inspect_run(root, project, env, envelope)
    cli(root, project, env, "doctor")
    print(f"PASS: copied Claude procedures, {domain}, no Beads/MCP, removal retains evidence")


def go_checks(root, project, env):
    (project / "go.mod").write_text("module example.test/claude\ngo 1.22\n")
    source = project / "quantity.go"
    source.write_text("package demo\nfunc Remaining(a, b int) int { return a + b }\n")
    (project / "quantity_test.go").write_text(
        'package demo\nimport "testing"\nfunc TestRemaining(t *testing.T) { '
        'if Remaining(10, 3) != 7 { t.Fatal("expected 7 remaining") } }\n'
    )
    failed = cli(root, project, env, "check", "verify", expected=1)
    source.write_text(source.read_text().replace("a + b", "a - b"))
    return [failed, cli(root, project, env, "check", "verify")]


def odoo_checks(root, project, env):
    module = project / "addons/custom"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(repr({"name": "Custom", "depends": ["base"]}))
    passed = cli(root, project, env, "check", "verify")
    blocked = cli(
        root,
        project,
        env,
        "run",
        "odoo.module.validate",
        "--args",
        '{"strict_dependencies":true}',
        expected=2,
    )
    assert blocked["result"]["reason"] == "INCOMPLETE_INVENTORY"
    assert blocked["result"]["data"]["dependency_counts"]["unknown"] > 0
    return [passed, blocked]


def main():
    root, wheels, constraints = map(Path, sys.argv[1:])
    for domain in ("go", "odoo"):
        target = root / domain
        target.mkdir(parents=True)
        exercise(target, wheels, constraints, domain)


if __name__ == "__main__":
    main()
