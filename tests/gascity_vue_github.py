"""An isolated Vue fixture branch in the operator-selected private test repository."""

import hashlib
import json
import os
import re

from tests.gascity_github import gh, publication_context
from tests.test_gascity_odoo_checks import git

BASE = "acceptance/vue-fixture-v2"


def target():
    repository = os.environ.get("DEVKIT_VUE_GITHUB_REPO")
    if repository is None:
        return None
    assert re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
    assert os.environ.get("DEVKIT_VUE_LIVE") == "1", "Private qualification requires a live session"
    assert gh("repo", "view", repository, "--json", "nameWithOwner,isPrivate") == dict(
        nameWithOwner=repository, isPrivate=True
    )
    return repository


def seed(workspace):
    repository = target()
    if repository is None:
        return
    git(workspace.repo, "remote", "add", "origin", "https://github.com/" + repository + ".git")
    if git(workspace.repo, "ls-remote", "origin", "refs/heads/" + BASE):
        git(workspace.repo, "fetch", "origin", BASE)
        assert git(workspace.repo, "rev-parse", "origin/" + BASE + "^{tree}") == git(
            workspace.repo, "rev-parse", "HEAD^{tree}"
        ), "The private Vue fixture branch differs; do not overwrite it"
        assert not git(workspace.repo, "status", "--porcelain=v1")
        # Reset only this owned disposable fixture after comparing its entire tree.
        git(workspace.repo, "reset", "--hard", "origin/" + BASE)
    else:
        git(workspace.repo, "push", "origin", "HEAD:refs/heads/" + BASE)


def destination(task):
    repository = target()
    return (
        {}
        if repository is None
        else dict(
            github=dict(
                repo=repository,
                remote="origin",
                base=BASE,
                head="devkit/vue-" + task,
                protected_branches=[],
            )
        )
    )


def prepare_publication(workspace, task, root, report):
    repository = target()
    if repository is None:
        return
    branch = "devkit/vue-" + task
    assert (
        gh("pr", "list", "--repo", repository, "--head", branch, "--state", "all", "--json", "url")
        == []
    )
    git(workspace.worktree, "push", "origin", report["commit"] + ":refs/heads/" + branch)
    assert (
        git(workspace.worktree, "ls-remote", "origin", "refs/heads/" + branch).split()[0]
        == report["commit"]
    )
    assert hashlib.sha256(report["body"].encode()).hexdigest() == report["body_sha256"]
    context = publication_context(workspace, task, root, report, repository)
    context.update(stack="vue", branch=branch, base=BASE)
    path = workspace.root / "operator-publication-vue.json"
    path.write_text(json.dumps(context, indent=2) + "\n")
    path.chmod(0o600)
    print("Checked Vue draft text awaits approval: " + str(path), flush=True)
