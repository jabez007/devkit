"""Opt-in native Gas City graph and installed Odoo check bundle acceptance."""

import json
import os
import runpy
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import gascity_github
from tests.gascity_odoo_live import devcontainer, implement
from tests.test_gascity_odoo_checks import git
from tests.test_odoo_runtime_acceptance import (
    installed_runtime_image as installed_runtime_image,
)
from tests.test_odoo_runtime_acceptance import (
    prepare_project,
)
from tests.test_odoo_runtime_reporting import docker
from tests.test_odoo_runtime_reporting import runtime_server as runtime_server

ROOT = Path(__file__).resolve().parents[1]
Spike = runpy.run_path(str(ROOT / "scripts/check_gascity_spike.py"))["Spike"]
PACK = ROOT / "integrations/gascity/odoo"
pytestmark = [
    pytest.mark.odoo_runtime,
    pytest.mark.skipif(
        os.environ.get("DEVKIT_GASCITY_ACCEPTANCE") != "1",
        reason="Set DEVKIT_GASCITY_ACCEPTANCE=1 and the pinned native tool paths",
    ),
]


@pytest.fixture(scope="module")
def delivery_image(request, tmp_path_factory):
    image_base = request.getfixturevalue("installed_runtime_image")
    context = tmp_path_factory.mktemp("odoo-delivery-image")
    (context / "Dockerfile").write_text(
        f"FROM {image_base}\nUSER root\n"
        "RUN apt-get update && apt-get install -y --no-install-recommends git && "
        "rm -rf /var/lib/apt/lists/*\nUSER odoo\n"
    )
    image = "devkit-odoo-delivery:" + uuid.uuid4().hex[:12]
    try:
        docker("build", "--tag", image, str(context), timeout=180)
        yield image
    finally:
        subprocess.run(["docker", "image", "rm", image], capture_output=True)


@pytest.fixture
def city(tmp_path):
    args = SimpleNamespace(root=tmp_path / "qualification", live=False)
    for key in ("gc", "bd", "dolt", "gascity_source"):
        setattr(args, key, Path(os.environ["DEVKIT_" + key.upper()]).resolve())
    spike = Spike(args)
    try:
        spike.prepare_city()
        pack = spike.city / "pack.toml"
        pack.write_text(
            pack.read_text()
            .replace("imports.spike", "imports.odoo")
            .replace(str(ROOT / "examples/gascity-spike"), str(PACK))
        )
        config = spike.city / "city.toml"
        config.write_text(
            config.read_text().replace(
                'native_transport="off"', 'native_transport="off"\nproxied_idle_timeout="1h"'
            )
        )
        yield spike
    finally:
        spike.cleanup()


def setup_task(city):
    prepare_project(city.repo, "pass")
    (city.repo / ".gitignore").write_text(".claude/\n.gc/\n.mcp.json\nstate/\n__pycache__/\n")
    if os.environ.get("DEVKIT_DELIVERY_LIVE") == "1":
        devcontainer(city.repo)
    addon = city.repo / "addons/sample"
    (addon / "action.xml").write_text(
        '<odoo><record id="action_delivery" model="ir.actions.act_window">'
        '<field name="name">Delivery contacts</field>'
        '<field name="res_model">res.partner</field>'
        '<field name="view_mode">list,form</field></record></odoo>'
    )
    (addon / "menu.xml").write_text(
        '<odoo><menuitem id="menu_delivery" name="Delivery" '
        'action="sample.action_delivery"/></odoo>'
    )
    manifest = dict(
        name="Sample",
        version="19.0.1.0.0",
        depends=["base", "web"],
        data=["menu.xml", "action.xml"],
        license="GPL-3",
    )
    (addon / "__manifest__.py").write_text(repr(manifest))
    git(city.repo, "init", "-q", "--initial-branch=main")
    git(city.repo, "config", "user.name", "Devkit Qualification")
    git(city.repo, "config", "user.email", "qualification@example.invalid")
    git(city.repo, "config", "commit.gpgSign", "false")
    git(city.repo, "add", ".")
    git(city.repo, "commit", "-qm", "Synthetic install-order defect")
    gascity_github.seed(city)
    base = git(city.repo, "rev-parse", "HEAD")
    task = city.gc(
        "bd", "create", "Fresh addon installation", "--type", "task", "--json", structured=True
    )["id"]
    brief = city.root / "brief.json"
    brief.write_text(
        json.dumps(
            dict(
                schema_version=1,
                task_id=task,
                problem="A fresh installation fails.",
                acceptance_criteria=[
                    "The delivery menu opens contacts after a fresh installation."
                ],
                approach="Load prerequisite data before data that refers to it.",
                scope=dict(in_scope=["Delivery access"], out_of_scope=["Other applications"]),
                open_questions=[],
            )
        )
    )
    cooked = city.gc(
        "formula",
        "cook",
        "devkit-odoo-delivery",
        "--attach",
        task,
        "--var",
        "task=" + task,
        "--var",
        "brief_file=" + str(brief),
        "--json",
        structured=True,
    )
    root, ids = cooked["root_id"], cooked["id_mapping"]
    city.gc(
        "worktree",
        "ensure",
        "--repo",
        city.repo,
        "--root",
        city.worktree.parent,
        "--path",
        city.worktree,
        "--base",
        "HEAD",
        "--bead",
        root,
        "--branch",
        "devkit/" + task,
        "--store-ref",
        "city",
        "--owner",
        "devkit-test",
        "--creator",
        "gc-worktree-ensure",
        "--generation",
        "acceptance-1",
        "--agent",
        "odoo.implementer",
        "--json",
        structured=True,
    )
    city.gc(
        "bd",
        "update",
        root,
        "--set-metadata",
        "gc.work_dir=" + str(city.worktree),
        "--json",
        structured=True,
    )
    return task, brief, root, ids, manifest, base


def bind_job(city, task, root, base, network, image):
    operator = city.root / "operator/devkit"
    operator.mkdir(parents=True)
    effects = ["read_fs", "write_fs", "execute_process", "network_read", "network_write"]
    (operator / "policy.toml").write_text(
        '[trusted_plugins]\nmccann-hub-devkit-odoo="0.7.0"\n'
        + "".join(
            f'\n[commands."{name}"]\nproject={json.dumps(str(city.worktree))}\n'
            f'effects={json.dumps(grants)}\nsurfaces=["cli"]\n'
            for name, grants in (
                ("odoo.module.test", effects),
                ("odoo.module.version.check", effects[:3]),
            )
        )
    )
    (operator / "policy.toml").chmod(0o600)
    runner = [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--entrypoint",
        "/usr/bin/env",
    ]
    for key, value in dict(
        HOME="/tmp",
        USER="devkit",
        LOGNAME="devkit",
        PGHOST="postgres",
        PGUSER="odoo",
        XDG_CONFIG_HOME="/operator",
        XDG_STATE_HOME=str(city.root / "state"),
        PATH="/opt/devkit/bin:/usr/local/bin:/usr/bin:/bin",
    ).items():
        runner.extend(["--env", key + "=" + value])
    runner.extend(
        [
            "--mount",
            f"type=bind,src={city.root},dst={city.root}",
            "--mount",
            f"type=bind,src={operator.parent},dst=/operator,readonly",
            image,
        ]
    )
    job = city.root / "job.json"
    job.write_text(
        json.dumps(
            dict(
                project=str(city.worktree),
                base_commit=base,
                addons_paths=["addons"],
                runner=runner,
                artifacts=str(city.root / "checks"),
                **gascity_github.destination(task),
            )
        )
    )
    return city.run(
        city.args.gc,
        "odoo",
        "delivery",
        "bind",
        job,
        "--task",
        task,
        "--workflow",
        root,
        structured=True,
    )


def test_native_approval_red_retry_and_installed_runtime_release(city, request, delivery_image):
    network, _ = request.getfixturevalue("runtime_server")
    task, brief, root, ids, manifest, base = setup_task(city)
    bind_job(city, task, root, base, network, delivery_image)
    bound = city.run(
        city.args.gc,
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
    city.close(ids["devkit-odoo-delivery.brief"])
    assert ids["devkit-odoo-delivery.spec"] not in city.ready()
    city.run(
        city.args.gc,
        "base",
        "brief",
        "approve",
        "--workflow",
        root,
        "--sha256",
        bound["sha256"],
        structured=True,
    )
    assert ids["devkit-odoo-delivery.spec"] in city.ready()
    city.close(ids["devkit-odoo-delivery.spec"])
    manifest["version"] = "19.0.1.0.1"
    path = city.worktree / "addons/sample/__manifest__.py"
    path.write_text(repr(manifest))
    git(city.worktree, "add", ".")
    git(city.worktree, "commit", "-qm", "Synthetic red attempt")
    city.close(ids["devkit-odoo-delivery.implement.iteration.1"])
    control = city.gc("convoy", "control", ids["devkit-odoo-delivery.implement"], timeout=180)
    assert ids["devkit-odoo-delivery.draft-pr"] not in city.ready()
    first = list((city.root / "checks").glob("checks-*/results.json"))
    assert len(first) == 1, (
        control,
        city.gc("bd", "list", "--all", "--include-ephemeral", "--limit", "0", "--json"),
    )
    red = json.loads(first[0].read_text())
    assert red["status"] == "failed", red
    assert [item["name"] for item in red["checks"]] == ["versions", "static-sample"]
    assert red["checks"][1]["result"]["reason"] == "INVALID_LOAD_ORDER"
    if repository := gascity_github.target():
        gascity_github.no_pull_requests(repository)
    beads = city.gc(
        "bd", "list", "--all", "--include-ephemeral", "--limit", "0", "--json", structured=True
    )
    attempt = [
        item["id"]
        for item in beads
        if item.get("metadata", {}).get("gc.step_ref", "").endswith("implement.iteration.2")
    ]
    assert len(attempt) == 1
    if os.environ.get("DEVKIT_DELIVERY_LIVE") == "1":
        implement(city, root, task, attempt[0])
        assert git(city.worktree, "rev-parse", "HEAD") != red["commit"]
        assert not git(city.worktree, "status", "--porcelain=v1")
        assert city.gc("bd", "show", attempt[0], "--json", structured=True)[0]["status"] == "closed"
    else:
        manifest["data"] = ["action.xml", "menu.xml"]
        path.write_text(repr(manifest))
        git(city.worktree, "add", ".")
        git(city.worktree, "commit", "-qm", "Load the action before its delivery menu")
        city.close(attempt[0])
    city.gc("convoy", "control", ids["devkit-odoo-delivery.implement"], timeout=240)
    assert ids["devkit-odoo-delivery.draft-pr"] in city.ready()
    bundles = [
        json.loads(item.read_text()) for item in (city.root / "checks").glob("*/results.json")
    ]
    green = [item for item in bundles if item["status"] == "success"]
    assert len(green) == 1, bundles
    assert [item["name"] for item in green[0]["checks"]] == [
        "versions",
        "static-sample",
        "runtime-sample",
    ]
    runtime = green[0]["checks"][-1]
    assert runtime["run_id"] and Path(runtime["evidence_path"]).is_file()
    assert runtime["result"]["data"]["tests"]["run"] >= 1
    assert runtime["result"]["data"]["cleanup"]["status"] == "complete"
    report = city.run(
        city.args.gc, "odoo", "delivery", "report", "--workflow", root, structured=True
    )
    assert green[0]["commit"] in report["body"]
    assert "runtime-sample: success" in report["body"]
    refused = subprocess.run(
        [
            str(city.args.gc),
            "odoo",
            "delivery",
            "publish",
            "--workflow",
            root,
            "--approved-body-sha256",
            report["body_sha256"],
        ],
        cwd=city.city,
        env={**city.env, "DEVKIT_UNATTENDED": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert refused.returncode == 75, refused.stdout + refused.stderr
    assert json.loads(refused.stdout)["reason"] == "HUMAN_PUBLICATION_REQUIRED"
    gascity_github.prepare_publication(city, task, root, report)
