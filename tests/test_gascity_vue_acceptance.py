"""Opt-in native approval, red retry and actual Vue tool/browser gate acceptance."""

import json
import os
import runpy
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_gascity_odoo_checks import git

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "integrations/gascity/vue"
Spike = runpy.run_path(str(ROOT / "scripts/check_gascity_spike.py"))["Spike"]
IMAGE = (
    "mcr.microsoft.com/playwright:v1.64.1-noble@"
    "sha256:2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f"
)
pytestmark = pytest.mark.skipif(
    os.environ.get("DEVKIT_VUE_ACCEPTANCE") != "1",
    reason="Needs native pinned tools, Docker and operator-installed locked Vue dependencies",
)


@pytest.fixture
def city(tmp_path):
    args = SimpleNamespace(root=tmp_path / "qualification", live=False)
    for name in ("gc", "bd", "dolt", "gascity_source"):
        setattr(args, name, Path(os.environ["DEVKIT_" + name.upper()]).resolve())
    workspace = Spike(args)
    try:
        workspace.prepare_city()
        pack = workspace.city / "pack.toml"
        pack.write_text(
            pack.read_text()
            .replace("imports.spike", "imports.vue")
            .replace(str(ROOT / "examples/gascity-spike"), str(PACK))
        )
        yield workspace
    finally:
        workspace.cleanup()


def setup_task(workspace):
    shutil.copytree(ROOT / "tests/fixtures/vue", workspace.repo)
    git(workspace.repo, "init", "-q", "--initial-branch=main")
    for key, value in (
        ("user.name", "Devkit Qualification"),
        ("user.email", "qualification@example.invalid"),
        ("commit.gpgSign", "false"),
    ):
        git(workspace.repo, "config", key, value)
    git(workspace.repo, "add", ".")
    git(workspace.repo, "commit", "-qm", "Synthetic Vue counter defect")
    task = workspace.gc(
        "bd", "create", "Counter advances twice", "--type", "task", "--json", structured=True
    )["id"]
    brief = workspace.root / "brief.json"
    brief.write_text(
        json.dumps(
            dict(
                schema_version=1,
                task_id=task,
                problem="The counter advances twice after one activation.",
                acceptance_criteria=[
                    "Each pointer or keyboard activation increases the displayed count by one."
                ],
                approach="Preserve the existing accessible button interaction.",
                scope=dict(in_scope=["Counter behavior"], out_of_scope=["Other screens"]),
                open_questions=[],
            )
        )
    )
    cooked = workspace.gc(
        "formula",
        "cook",
        "devkit-vue-delivery",
        "--attach",
        task,
        "--var",
        "task=" + task,
        "--var",
        "brief_file=" + str(brief),
        "--json",
        structured=True,
    )
    root = cooked["root_id"]
    workspace.gc(
        "worktree",
        "ensure",
        "--repo",
        workspace.repo,
        "--root",
        workspace.worktree.parent,
        "--path",
        workspace.worktree,
        "--base",
        "HEAD",
        "--bead",
        root,
        "--branch",
        "devkit/vue-" + task,
        "--store-ref",
        "city",
        "--owner",
        "devkit-test",
        "--creator",
        "gc-worktree-ensure",
        "--generation",
        "vue-acceptance-1",
        "--agent",
        "vue.implementer",
        "--json",
        structured=True,
    )
    workspace.gc(
        "bd",
        "update",
        root,
        "--set-metadata",
        "gc.work_dir=" + str(workspace.worktree),
        "--json",
        structured=True,
    )
    dependencies = Path(os.environ["DEVKIT_VUE_NODE_MODULES"]).resolve()
    assert (
        json.loads((workspace.repo / "package-lock.json").read_text())["packages"][""][
            "devDependencies"
        ]
        == json.loads((dependencies.parent / "package.json").read_text())["devDependencies"]
    )
    shutil.copytree(dependencies, workspace.worktree / "node_modules", symlinks=True)
    return task, brief, root, cooked["id_mapping"]


def bind_job(workspace, task, root):
    runner = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--entrypoint",
        "/usr/bin/env",
        "--env",
        "HOME=/tmp",
        "--env",
        "CI=1",
        "--workdir",
        str(workspace.worktree),
        "--mount",
        f"type=bind,src={workspace.root},dst={workspace.root}",
        IMAGE,
    ]
    path = workspace.root / "job.json"
    path.write_text(
        json.dumps(
            dict(
                project=str(workspace.worktree),
                runner=runner,
                artifacts=str(workspace.root / "checks"),
            )
        )
    )
    return workspace.run(
        workspace.args.gc,
        "vue",
        "delivery",
        "bind",
        path,
        "--task",
        task,
        "--workflow",
        root,
        structured=True,
    )


def approve(workspace, task, brief, root, ids):
    saved = workspace.run(
        workspace.args.gc,
        "base",
        "brief",
        "record",
        brief,
        "--task",
        task,
        "--workflow",
        root,
        structured=True,
    )
    workspace.close(ids["devkit-vue-delivery.brief"])
    assert ids["devkit-vue-delivery.spec"] not in workspace.ready()
    workspace.run(
        workspace.args.gc,
        "base",
        "brief",
        "approve",
        "--workflow",
        root,
        "--sha256",
        saved["sha256"],
        structured=True,
    )
    assert ids["devkit-vue-delivery.spec"] in workspace.ready()
    workspace.close(ids["devkit-vue-delivery.spec"])


def test_native_vue_approval_red_retry_and_browser_gate(city):
    task, brief, root, ids = setup_task(city)
    bind_job(city, task, root)
    approve(city, task, brief, root, ids)
    city.close(ids["devkit-vue-delivery.implement.iteration.1"])
    city.gc("convoy", "control", ids["devkit-vue-delivery.implement"], timeout=240)
    assert ids["devkit-vue-delivery.draft-pr"] not in city.ready()
    red = [json.loads(p.read_text()) for p in (city.root / "checks").glob("*/results.json")]
    assert len(red) == 1 and red[0]["status"] == "failed", red
    assert red[0]["checks"][0]["result"]["data"]["tests"]["failed"] == 1
    beads = city.gc(
        "bd", "list", "--all", "--include-ephemeral", "--limit", "0", "--json", structured=True
    )
    attempts = [
        bead["id"]
        for bead in beads
        if bead.get("metadata", {}).get("gc.step_ref", "").endswith("implement.iteration.2")
    ]
    assert len(attempts) == 1
    path = city.worktree / "src/CounterButton.vue"
    path.write_text(path.read_text().replace("count += 2", "count += 1"))
    git(city.worktree, "add", "src/CounterButton.vue")
    git(city.worktree, "commit", "-qm", "Advance the counter once per activation")
    city.close(attempts[0])
    city.gc("convoy", "control", ids["devkit-vue-delivery.implement"], timeout=240)
    assert ids["devkit-vue-delivery.draft-pr"] in city.ready()
    metadata = city.gc("bd", "show", root, "--json", structured=True)[0]["metadata"]
    green = json.loads(Path(metadata["devkit.delivery.checks"]).read_text())
    assert green["status"] == "success", green
    assert [check["name"] for check in green["checks"]] == [
        "vitest",
        "eslint",
        "vue-tsc",
        "playwright",
    ]
    assert green["checks"][-1]["result"]["data"]["tests"] == dict(run=1, failed=0, skipped=0)
    report = city.run(
        city.args.gc, "vue", "delivery", "report", "--workflow", root, structured=True
    )
    assert report["commit"] == git(city.worktree, "rev-parse", "HEAD")
    assert "playwright: success" in report["body"]
