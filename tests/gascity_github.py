"""Explicit private-repository qualification, ending before PR text approval."""

import json
import os
import re
import subprocess

from tests.test_gascity_odoo_checks import git


def target():
    value = os.environ.get("DEVKIT_DELIVERY_GITHUB_REPO")
    if value is None:
        return None
    assert re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value), "Use owner/repository"
    assert os.environ.get("DEVKIT_DELIVERY_LIVE") == "1", "GitHub qualification needs the live run"
    return value


def gh(*arguments):
    result = subprocess.run(
        ["gh", *arguments],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    )
    return json.loads(result.stdout)


def no_pull_requests(repository):
    assert gh("pr", "list", "--repo", repository, "--state", "all", "--json", "url") == [], (
        "Use a dedicated acceptance repository with no pull requests"
    )


def seed(city):
    repository = target()
    if repository is None:
        return
    info = gh("repo", "view", repository, "--json", "nameWithOwner,isPrivate")
    assert info == {"nameWithOwner": repository, "isPrivate": True}, "Use a private repository"
    no_pull_requests(repository)
    git(city.repo, "remote", "add", "origin", "https://github.com/" + repository + ".git")
    remote = git(city.repo, "ls-remote", "origin", "refs/heads/main")
    if remote:
        git(city.repo, "fetch", "origin", "main")
        expected = git(city.repo, "rev-parse", "HEAD^{tree}")
        assert git(city.repo, "rev-parse", "origin/main^{tree}") == expected, (
            "The private repository's main branch differs from the synthetic seed"
        )
        assert not git(city.repo, "status", "--porcelain=v1")
        # Only this newly-created, clean fixture is reset, after exact tree comparison.
        git(city.repo, "reset", "--hard", "origin/main")
    else:
        assert not git(city.repo, "ls-remote", "--heads", "origin"), "Use an empty repository"
        git(city.repo, "push", "--set-upstream", "origin", "main")
    git(city.repo, "remote", "set-head", "origin", "main")


def destination(task):
    repository = target()
    if repository is None:
        return {}
    return {
        "github": dict(
            repo=repository,
            remote="origin",
            base="main",
            head="devkit/" + task,
            protected_branches=[],
        )
    }


def prepare_publication(city, task, root, report):
    repository = target()
    if repository is None:
        return
    no_pull_requests(repository)
    git(
        city.worktree,
        "push",
        "--set-upstream",
        "origin",
        report["commit"] + ":refs/heads/devkit/" + task,
    )
    remote = git(city.worktree, "ls-remote", "origin", "refs/heads/devkit/" + task)
    assert remote.split()[0] == report["commit"]
    context = {
        "repository": repository,
        "city": str(city.city),
        "task": task,
        "workflow": root,
        "worktree": str(city.worktree),
        "report": report,
        "environment": {
            key: city.env[key]
            for key in (
                "PATH",
                "HOME",
                "USER",
                "LOGNAME",
                "GC_HOME",
                "DOLT_ROOT_PATH",
                "XDG_CACHE_HOME",
                "XDG_CONFIG_HOME",
                "XDG_STATE_HOME",
                "DO_NOT_TRACK",
                "BD_DISABLE_METRICS",
            )
            if key in city.env
        },
    }
    path = city.root / "operator-publication.json"
    path.write_text(json.dumps(context, indent=2) + "\n")
    path.chmod(0o600)
    print("Private GitHub qualification prepared for PR text review: " + str(path), flush=True)
