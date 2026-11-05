"""Opt-in round two in the retained private qualification, before text publication."""

import json
import os
import subprocess
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.gascity_github import gh
from tests.gascity_live import implement
from tests.gascity_odoo_live import PROFILE
from tests.test_gascity_feedback_acceptance import feedback_command
from tests.test_gascity_odoo_acceptance import PACK, Spike, bind_job
from tests.test_gascity_odoo_acceptance import delivery_image as delivery_image
from tests.test_gascity_odoo_acceptance import installed_runtime_image as installed_runtime_image
from tests.test_gascity_odoo_acceptance import runtime_server as runtime_server
from tests.test_gascity_odoo_checks import git

pytestmark = [
    pytest.mark.odoo_runtime,
    pytest.mark.skipif(
        not os.environ.get("DEVKIT_DELIVERY_RESUME_CONTEXT"),
        reason="Needs an explicitly selected retained private qualification and draft PR",
    ),
]


@pytest.fixture
def retained_city():
    context_path = Path(os.environ["DEVKIT_DELIVERY_RESUME_CONTEXT"]).resolve()
    context = json.loads(context_path.read_text())
    info = gh("repo", "view", context["repository"], "--json", "nameWithOwner,isPrivate")
    assert info == {"nameWithOwner": context["repository"], "isPrivate": True}
    args = SimpleNamespace(root=context_path.parent, live=False)
    for name in ("gc", "bd", "dolt", "gascity_source"):
        setattr(args, name, Path(os.environ["DEVKIT_" + name.upper()]).resolve())
    workspace = Spike(args, resume=True)
    assert str(workspace.city) == context["city"]
    assert str(workspace.worktree) == context["worktree"]
    assert git(workspace.worktree, "branch", "--show-current") == "devkit/" + context["task"]
    assert not git(workspace.worktree, "status", "--porcelain=v1")
    pack = workspace.city / "pack.toml"
    previous = tomllib.loads(pack.read_text())["imports"]["odoo"]["source"]
    pack.write_text(pack.read_text().replace(json.dumps(previous), json.dumps(str(PACK))))
    try:
        yield workspace, context
    finally:
        workspace.cleanup()


def selection(task, root, number):
    return ["--task", task, "--workflow", root, "--round", str(number)]


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def prepare_round(workspace, context, url):
    task, previous = context["task"], context["workflow"]
    checkpoint = workspace.root / "round-two-workflow.json"
    if checkpoint.exists():
        return json.loads(checkpoint.read_text())
    feedback_command(
        workspace,
        "begin",
        "--task",
        task,
        "--workflow",
        previous,
        "--branch",
        "devkit/" + task,
        "--pr",
        url,
    )
    questions = workspace.root / "round-one-questions.json"
    save(
        questions,
        [
            dict(
                question="What should the menu be called?",
                assumption="Use Delivery.",
                reason="That is the existing label.",
            )
        ],
    )
    recorded = feedback_command(workspace, "questions", questions, *selection(task, previous, 1))
    answers = workspace.root / "round-one-answers.json"
    save(
        answers,
        [
            dict(
                question_id=recorded["ids"][0],
                accepted=False,
                answer="Call the menu Dispatch contacts.",
            )
        ],
    )
    feedback_command(workspace, "answers", answers, *selection(task, previous, 1))
    proposal = workspace.root / "round-two-brief.json"
    feedback_command(workspace, "draft", proposal, *selection(task, previous, 1))
    cooked = workspace.gc(
        "formula",
        "cook",
        "devkit-odoo-delivery",
        "--attach",
        task,
        "--var",
        "task=" + task,
        "--var",
        "brief_file=" + str(proposal),
        "--json",
        structured=True,
    )
    # Persist the native handle before advancing. A retry must not cook another workflow.
    save(checkpoint, cooked)
    return cooked


def approve_round(workspace, context, cooked):
    task, previous, root = context["task"], context["workflow"], cooked["root_id"]
    state = feedback_command(
        workspace,
        "next",
        workspace.root / "round-two-brief.json",
        *selection(task, previous, 1),
        "--next-workflow",
        root,
    )
    assert state["round"] == 2 and state["branch"] == "devkit/" + task
    workspace.gc(
        "bd",
        "update",
        root,
        "--set-metadata",
        "gc.work_dir=" + str(workspace.worktree),
        "--json",
        structured=True,
    )
    ids = cooked["id_mapping"]
    spec = ids["devkit-odoo-delivery.spec"]
    if workspace.gc("bd", "show", spec, "--json", structured=True)[0]["status"] == "closed":
        return state
    workspace.close(ids["devkit-odoo-delivery.brief"])
    assert spec not in workspace.ready()
    pending = subprocess.run(
        [str(workspace.args.gc), "base", "brief", "resume", "--task", task],
        cwd=workspace.city,
        env=workspace.env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert pending.returncode == 2
    assert json.loads(pending.stdout)["reason"] == "BRIEF_PENDING_APPROVAL"
    workspace.run(
        workspace.args.gc,
        "base",
        "brief",
        "approve",
        "--workflow",
        root,
        "--sha256",
        state["brief_sha256"],
        structured=True,
    )
    assert spec in workspace.ready()
    workspace.close(spec)
    return state


def export_review(workspace, context, root, url):
    report = workspace.run(
        workspace.args.gc, "odoo", "delivery", "report", "--workflow", root, structured=True
    )
    assert "Round: 2" in report["body"]
    assert "Call the menu Dispatch contacts." in report["body"]
    assert "Assumption: Use Delivery." in report["body"]
    assert "Reason: That is the existing label." in report["body"]
    git(
        workspace.worktree,
        "push",
        "origin",
        report["commit"] + ":refs/heads/devkit/" + context["task"],
    )
    # GitHub may briefly report the prior PR head after accepting a branch push.
    deadline = time.monotonic() + 30
    value = gh("pr", "view", url, "--json", "url,isDraft,headRefOid,body")
    while value["headRefOid"] != report["commit"] and time.monotonic() < deadline:
        time.sleep(1)
        value = gh("pr", "view", url, "--json", "url,isDraft,headRefOid,body")
    assert value["url"] == url and value["isDraft"] and value["headRefOid"] == report["commit"]
    assert value["body"] == context["report"]["body"], "PR text changed before approval"
    assert (
        len(gh("pr", "list", "--repo", context["repository"], "--state", "all", "--json", "url"))
        == 1
    )
    path = workspace.root / "operator-publication-round2.json"
    save(
        path,
        {
            **context,
            "workflow": root,
            "previous_workflow": context["workflow"],
            "round": 2,
            "pr": url,
            "report": report,
        },
    )
    print("Round two checked; exact PR text awaits approval: " + str(path), flush=True)


def test_live_answer_round_reuses_private_branch_and_draft(retained_city, request):
    workspace, context = retained_city
    task = context["task"]
    value = gh(
        "pr",
        "list",
        "--repo",
        context["repository"],
        "--state",
        "all",
        "--json",
        "url,isDraft,state,headRefName",
    )
    assert len(value) == 1 and value[0]["isDraft"] and value[0]["state"] == "OPEN"
    assert value[0]["headRefName"] == "devkit/" + task
    url = value[0]["url"]
    cooked = prepare_round(workspace, context, url)
    state = approve_round(workspace, context, cooked)
    assert state["pr"] == url
    root, ids = cooked["root_id"], cooked["id_mapping"]
    draft = ids["devkit-odoo-delivery.draft-pr"]
    if draft not in workspace.ready():
        network, _ = request.getfixturevalue("runtime_server")
        bind_job(
            workspace,
            task,
            root,
            context["report"]["commit"],
            network,
            request.getfixturevalue("delivery_image"),
            github=dict(
                repo=context["repository"],
                remote="origin",
                base="main",
                head="devkit/" + task,
                protected_branches=[],
            ),
        )
        implement(workspace, root, task, ids["devkit-odoo-delivery.implement.iteration.1"], PROFILE)
        assert not git(workspace.worktree, "status", "--porcelain=v1")
        assert git(workspace.worktree, "rev-parse", "HEAD") != context["report"]["commit"]
        workspace.gc("convoy", "control", ids["devkit-odoo-delivery.implement"], timeout=240)
        assert draft in workspace.ready()
    metadata = workspace.gc("bd", "show", root, "--json", structured=True)[0]["metadata"]
    bundle = json.loads(Path(metadata["devkit.delivery.checks"]).read_text())
    runtime = bundle["checks"][-1]["result"]["data"]
    assert bundle["status"] == "success" and runtime["tests"]["run"] >= 1
    assert runtime["tests"]["failed"] == 0 and runtime["cleanup"]["status"] == "complete"
    export_review(workspace, context, root, url)
