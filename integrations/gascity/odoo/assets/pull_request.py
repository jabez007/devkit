"""Prepare reviewable text and publish only the operator-approved checked revision."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from checks import DeliveryError, commit, environment, git, save


def prepare(job, reference, bundle, brief):
    if bundle.get("status") != "success" or bundle.get("brief") != reference:
        raise DeliveryError("CHECKS_NOT_PASSED")
    if commit(job["project"]) != bundle.get("commit"):
        raise DeliveryError("CHECKED_COMMIT_CHANGED")
    body = [
        brief["problem"],
        "",
        "## Acceptance criteria",
        "",
        *["- " + criterion for criterion in brief["acceptance_criteria"]],
        "",
        "## Checks",
        "",
        "Checked commit: `" + bundle["commit"] + "`.",
        "",
    ]
    for item in bundle["checks"]:
        body.append(
            "- " + item["name"] + ": " + item["result"]["status"] + ". " + item["result"]["summary"]
        )
    body.extend(["", "## Open questions", ""])
    body.extend(["- " + question for question in brief.get("open_questions", [])] or ["None."])
    body.extend(
        [
            "",
            "Selected task: `" + reference["task_id"] + "`.",
            "Approved brief: `" + reference["sha256"] + "`.",
            "",
        ]
    )
    text = "\n".join(body)
    directory = Path(bundle["directory"])
    path = directory / "pull-request.md"
    raw = text.encode("utf-8")
    if path.exists():
        if path.read_bytes() != raw:
            raise DeliveryError("PR_BODY_CHANGED")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o400)
    return {
        "status": "success",
        "commit": bundle["commit"],
        "body_file": str(path),
        "body_sha256": hashlib.sha256(raw).hexdigest(),
        "title": brief["problem"].strip().splitlines()[0][:100],
        "body": text,
    }


def gh(job, *args):
    try:
        result = subprocess.run(
            ["gh", *args],
            cwd=job["project"],
            env=environment(),
            capture_output=True,
            timeout=120,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DeliveryError("GITHUB_UNAVAILABLE") from error
    if result.returncode or len(result.stdout) > 1_000_000:
        raise DeliveryError("GITHUB_UNAVAILABLE")
    return result.stdout.strip()


def _target(job):
    target = job.get("github")
    if target is None:
        raise DeliveryError("GITHUB_TARGET_REQUIRED")
    if git(job["project"], "branch", "--show-current") != target["head"]:
        raise DeliveryError("BRANCH_MISMATCH")
    remote = git(job["project"], "remote", "get-url", "--push", target["remote"])
    repo = target["repo"]
    allowed = [
        prefix + repo + suffix
        for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/")
        for suffix in ("", ".git")
    ]
    if remote not in allowed:
        raise DeliveryError("GITHUB_REMOTE_MISMATCH")
    return target


def publish(job, report, approved_hash):
    if "DEVKIT_UNATTENDED" in os.environ:
        raise DeliveryError("HUMAN_PUBLICATION_REQUIRED")
    if approved_hash != report["body_sha256"]:
        raise DeliveryError("PR_BODY_APPROVAL_REQUIRED")
    if commit(job["project"]) != report["commit"]:
        raise DeliveryError("CHECKED_COMMIT_CHANGED")
    target = _target(job)
    existing = json.loads(
        gh(
            job,
            "pr",
            "list",
            "--repo",
            target["repo"],
            "--head",
            target["head"],
            "--base",
            target["base"],
            "--state",
            "all",
            "--limit",
            "2",
            "--json",
            "url,isDraft,state,headRefOid,title,body",
        )
    )
    if existing:
        if len(existing) != 1:
            raise DeliveryError("EXISTING_PR_MISMATCH")
        return _receipt(existing[0], report)
    git(
        job["project"],
        "push",
        "--",
        target["remote"],
        report["commit"] + ":refs/heads/" + target["head"],
    )
    # Use a private file so Markdown newlines never pass through shell interpolation.
    url = gh(
        job,
        "pr",
        "create",
        "--repo",
        target["repo"],
        "--draft",
        "--head",
        target["head"],
        "--base",
        target["base"],
        "--title",
        report["title"],
        "--body-file",
        report["body_file"],
    )
    value = json.loads(
        gh(
            job,
            "pr",
            "view",
            url,
            "--repo",
            target["repo"],
            "--json",
            "url,isDraft,state,headRefOid,title,body",
        )
    )
    receipt = _receipt(value, report)
    path = Path(report["body_file"]).with_name("pull-request.json")
    if not path.exists():
        save(path, receipt)
    return receipt


def _receipt(value, report):
    if (
        not isinstance(value, dict)
        or value.get("isDraft") is not True
        or value.get("state") != "OPEN"
        or value.get("headRefOid") != report["commit"]
        or value.get("body") != report["body"]
        or value.get("title") != report["title"]
    ):
        raise DeliveryError("PUBLISHED_PR_MISMATCH")
    return {
        "status": "success",
        "url": value["url"],
        "draft": True,
        "commit": report["commit"],
        "body_sha256": report["body_sha256"],
    }
