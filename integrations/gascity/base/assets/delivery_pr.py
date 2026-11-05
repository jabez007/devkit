"""Prepare reviewable text and publish only the operator-approved checked revision."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from delivery_common import DeliveryError, commit, environment, git, save


def _check_line(item):
    result = item["result"]
    summary = result["summary"].splitlines()[0]
    data = result.get("data", {})
    tests = data.get("tests")
    if isinstance(tests, dict):
        summary += f"; {tests['run']} run, {tests['failed']} failed, {tests['skipped']} skipped"
        cleanup = data.get("cleanup", {}).get("status")
        if cleanup:
            summary += "; database cleanup " + cleanup
    return "- " + item["name"] + ": " + result["status"] + ". " + summary


def _question(item, answer=None):
    text = (
        "- "
        + item["question"]
        + " Assumption: "
        + item["assumption"]
        + " Reason: "
        + item["reason"]
    )
    if answer is not None:
        text += " Answer: " + ("Assumption accepted." if answer["accepted"] else answer["answer"])
    return text


def _questions(brief, feedback):
    current = feedback.get("questions", [])
    answers = {item["question_id"]: item for item in feedback.get("answers", [])}
    existing = {item["question"] for item in current}
    lines = ["- " + text for text in brief.get("open_questions", []) if text not in existing]
    lines.extend(_question(item) for item in current if item["id"] not in answers)
    result = ["", "## Open questions", "", *(lines or ["None."])]
    previous = {item["id"]: item for item in feedback.get("previous_questions", [])}
    resolved = [_question(item, answers[item["id"]]) for item in current if item["id"] in answers]
    resolved.extend(
        _question(previous[item["question_id"]], item)
        for item in feedback.get("previous_answers", [])
        if item["question_id"] in previous
    )
    if resolved:
        result.extend(["", "## Answers used", "", *resolved])
    return result


def prepare(job, reference, bundle, brief, *, feedback=None):
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
    if feedback:
        body.insert(2, "Round: " + str(feedback["round"]) + "\n")
    for item in bundle["checks"]:
        body.append(_check_line(item))
    body.extend(_questions(brief, feedback or {}))
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
    raw = text.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    path = directory / ("pull-request-" + digest + ".md")
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
        "body_sha256": digest,
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


def _push(job, report, target):
    git(
        job["project"],
        "push",
        "--",
        target["remote"],
        report["commit"] + ":refs/heads/" + target["head"],
    )


def _confirmed(job, report, target, url):
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
    return _saved(report, value)


def _saved(report, value):
    receipt = _receipt(value, report)
    path = Path(report["body_file"]).with_suffix(".json")
    if not path.exists():
        save(path, receipt)
    return receipt


def _existing(job, report, target, value, known_pr):
    if not isinstance(value, dict):
        raise DeliveryError("PUBLISHED_PR_MISMATCH")
    if known_pr is not None and value.get("url") != known_pr:
        raise DeliveryError("KNOWN_PR_MISMATCH")
    try:
        return _saved(report, value)
    except DeliveryError:
        if known_pr is None:
            raise
    if value.get("isDraft") is not True or value.get("state") != "OPEN":
        raise DeliveryError("PUBLISHED_PR_MISMATCH")
    _push(job, report, target)
    gh(
        job,
        "pr",
        "edit",
        known_pr,
        "--repo",
        target["repo"],
        "--title",
        report["title"],
        "--body-file",
        report["body_file"],
    )
    return _confirmed(job, report, target, known_pr)


def publish(job, report, approved_hash, *, known_pr=None):
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
        return _existing(job, report, target, existing[0], known_pr)
    if known_pr is not None:
        raise DeliveryError("KNOWN_PR_UNAVAILABLE")
    _push(job, report, target)
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
    return _confirmed(job, report, target, url)


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
