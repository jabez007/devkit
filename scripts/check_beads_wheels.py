"""Real Beads acceptance in disposable workspaces and independent wheel installs."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from check_beads_lifecycle import exercise as lifecycle
from check_wheels import absent, cli, install, policy, run

READ = ["read_fs", "write_fs", "execute_process", "network_read"]


def bd(binary, project, env, *args):
    result = subprocess.run(
        [str(binary), *args], cwd=project, env=env, capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout) if "--json" in args else result.stdout


def snapshot(directory):
    return {
        str(path.relative_to(directory)): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in directory.rglob("*")
        if path.is_file()
    }


def setup(root, wheels, constraints, domain, binary):
    project, env = install(
        root,
        wheels,
        [
            "mccann_hub.devkit",
            "mccann_hub.devkit_beads",
            f"mccann_hub.devkit_{domain}",
            "mccann_hub.devkit_mcp",
        ],
        constraints,
    )
    absent(
        root,
        project,
        env,
        ["odoo", "docker", "mccann_hub.devkit_odoo" if domain == "go" else "mccann_hub.devkit_go"],
    )
    home = root / "home"
    home.mkdir()
    env.update(
        HOME=str(home),
        BD_DISABLE_METRICS="1",
        BEADS_DIR=str(project / ".beads"),
        BD_ACTOR="devkit-acceptance",
        PATH=f"{binary.parent}:{env['PATH']}",
    )
    run("git", "init", "--quiet", str(project), env=env)
    bd(
        binary,
        project,
        env,
        "init",
        "--non-interactive",
        "--quiet",
        "--skip-agents",
        "--skip-hooks",
        "--prefix",
        "test",
    )
    item = bd(
        binary, project, env, "create", "Validate synthetic project", "--type", "task", "--json"
    )
    blocker = bd(binary, project, env, "create", "Review prerequisite", "--type", "task", "--json")
    bd(binary, project, env, "dep", "add", item["id"], blocker["id"], "--json")
    check = "go.tests" if domain == "go" else "odoo.manifests"
    (project / "devkit.toml").write_text(
        f'plugins=["beads","{domain}"]\ntimeout=90\n[profiles]\nverify=["{check}"]\n'
    )
    if domain == "go":
        (project / "go.mod").write_text("module example.test/beads\ngo 1.22\n")
        (project / "test_test.go").write_text(
            'package demo\nimport "testing"\nfunc TestWorks(t *testing.T) {}\n'
        )
    else:
        module = project / "addons/custom"
        module.mkdir(parents=True)
        (module / "__manifest__.py").write_text(repr({"name": "Custom", "depends": ["base"]}))
    commands = {
        f"beads.{name}": READ for name in ("workspace", "item.show", "ready", "dependencies")
    }
    commands["beads.evidence.associate"] = READ
    commands["go.test" if domain == "go" else "odoo.module.validate"] = (
        ["read_fs", "write_fs", "execute_process", "network_read", "network_write"]
        if domain == "go"
        else ["read_fs"]
    )
    policy(root, project, ["beads", domain], commands)
    return project, env, item, blocker


def association_parity(root, project, env, arguments, expected):
    code = """
import anyio, json, os, sys
from pathlib import Path
from mccann_hub.devkit.app import create_service
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
project, arguments, expected = Path(sys.argv[1]), json.loads(sys.argv[2]), json.loads(sys.argv[3])
assert create_service(project).execute("beads.evidence.associate",arguments)["result"] == expected
async def check():
    params = StdioServerParameters(
        command=sys.argv[4], args=["--project",str(project)], env=dict(os.environ))
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            result = await session.call_tool("beads.evidence.associate",arguments)
            assert result.structuredContent["result"] == expected
            envelope = result.structuredContent
            assert json.loads(Path(envelope["evidence_path"]).read_text())["result"] == expected
anyio.run(check)
"""
    run(
        str(root / "venv/bin/python"),
        "-c",
        code,
        str(project),
        json.dumps(arguments),
        json.dumps(expected),
        str(root / "venv/bin/devkit-mcp"),
        cwd=project,
        env=env,
    )


def exercise(root, wheels, constraints, domain, binary):
    project, env, item, blocker = setup(root, wheels, constraints, domain, binary)
    before = snapshot(project / ".beads")
    home_before = snapshot(root / "home")
    workspace = cli(root, project, env, "run", "beads.workspace")["result"]["data"]["workspace"]
    ref = f"beads:{workspace['project_id']}:{item['id']}"
    blocker_ref = f"beads:{workspace['project_id']}:{blocker['id']}"
    shown = cli(root, project, env, "run", "beads.item.show", "--args", json.dumps({"ref": ref}))
    assert shown["result"]["data"]["item"]["status"] == "open"
    ready = cli(root, project, env, "run", "beads.ready")["result"]["data"]["items"]
    assert [row["ref"] for row in ready] == [blocker_ref]
    deps = cli(root, project, env, "run", "beads.dependencies", "--args", json.dumps({"ref": ref}))
    assert deps["result"]["data"]["dependencies"][0]["ref"] == blocker_ref
    assert snapshot(root / "home") == home_before, "Beads reads changed user files"
    check = cli(root, project, env, "check", "verify")
    # Go is explicitly authorized to write its own caches. Compare Beads reads
    # separately from the domain verification's operational effects.
    home_before = snapshot(root / "home")
    original = Path(check["evidence_path"]).read_bytes()
    args = {"ref": ref, "run_id": check["run_id"]}
    linked = cli(root, project, env, "run", "beads.evidence.associate", "--args", json.dumps(args))
    assert linked["result"]["data"]["references"] == [ref]
    association_parity(root, project, env, args, linked["result"])
    stored = cli(root, project, env, "runs", "show", check["run_id"])["result"]["data"]
    assert stored["references"] == [ref]
    assert Path(check["evidence_path"]).read_bytes() == original
    prune = cli(
        root, project, env, "runs", "prune", "--older-than-days", "0", "--keep-last", "0", "--apply"
    )
    assert check["run_id"] not in prune["result"]["data"]["deleted"]
    assert Path(check["evidence_path"]).exists()
    after = snapshot(project / ".beads")
    assert {k: v[0] for k, v in after.items()} == {k: v[0] for k, v in before.items()}, (
        "Beads read operations changed workspace contents"
    )
    touched = [name for name in before if before[name] != after[name]]
    assert all(name.startswith(("embeddeddolt/", "dolt/")) for name in touched), touched
    if touched:
        print(f"INFO: {len(touched)} embedded Dolt bookkeeping files rewritten during inspection")
    assert snapshot(root / "home") == home_before, "Beads read operations changed user files"
    assert (
        bd(
            binary,
            project,
            env,
            "--readonly",
            "--sandbox",
            "list",
            "--id",
            item["id"],
            "--all",
            "--json",
        )[0]["status"]
        == "open"
    )
    lifecycle(root, project, env, ref)
    # Copy the existing portable bundle, including references, into a foundation-only install.
    portable(root, wheels, constraints, env, check["run_id"], ref)
    run(
        "uv",
        "pip",
        "uninstall",
        "--python",
        str(root / "venv/bin/python"),
        "mccann-hub-devkit-beads",
    )
    absent(root, project, env, ["mccann_hub.devkit_beads"])
    discovered = cli(root, project, env, "runs", "list", "--reference", ref)["result"]["data"]
    assert [row["run_id"] for row in discovered["runs"]] == [check["run_id"]]
    assert cli(root, project, env, "runs", "show", check["run_id"])["result"]["data"][
        "references"
    ] == [ref]
    print(
        f"PASS: real Beads 1.3.2 + {domain}, association parity/retries, "
        "retention, portable evidence"
    )


def portable(root, wheels, constraints, source_env, run_id, reference):
    target = root / "portable"
    target.mkdir()
    project, env = install(target, wheels, ["mccann_hub.devkit"], constraints)
    absent(
        target,
        project,
        env,
        ["mccann_hub.devkit_beads", "mccann_hub.devkit_go", "mccann_hub.devkit_odoo", "mcp"],
    )
    shutil.copytree(
        Path(source_env["XDG_STATE_HOME"]) / "devkit/runs", target / "state/devkit/runs"
    )
    shown = cli(target, project, env, "runs", "show", run_id, "--all-projects")["result"]["data"]
    assert shown["references"] == [reference]
    listed = cli(target, project, env, "runs", "list", "--reference", reference, "--all-projects")
    assert [row["run_id"] for row in listed["result"]["data"]["runs"]] == [run_id]
    assert shown["run"]["result"]["status"] == "success"
    assert "work_item_ref" in shown["run"] and shown["run"]["work_item_ref"] is None
    pruned = cli(
        target,
        project,
        env,
        "runs",
        "prune",
        "--all-projects",
        "--older-than-days",
        "0",
        "--keep-last",
        "0",
        "--apply",
    )
    assert run_id not in pruned["result"]["data"]["deleted"]


def main():
    root, wheels, constraints = map(Path, sys.argv[1:4])
    root.mkdir()
    binary = Path(os.environ["DEVKIT_BEADS_BINARY"]).resolve()
    assert binary.name == "bd" and binary.is_file(), (
        "Set DEVKIT_BEADS_BINARY to the pinned bd 1.3.2 executable"
    )
    for domain in ("go", "odoo"):
        target = root / f"beads_{domain}"
        target.mkdir()
        exercise(target, wheels, constraints, domain, binary)


if __name__ == "__main__":
    main()
