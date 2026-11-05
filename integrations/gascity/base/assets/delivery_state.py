"""Bind operator inputs and connect check artifacts to native Gas City task state."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from brief_format import BriefError
from brief_format import load as load_brief
from brief_state import _gc, _identity, _members, _selection, _show, _update
from delivery_common import DeliveryError, environment, git, save
from delivery_common import load_json as load
from delivery_pr import prepare, publish
from native_state import StateError, _pack

PREFIX = "devkit.delivery."
FEEDBACK = "devkit.feedback."


def _feedback(command, *arguments):
    result = _pack("base", "feedback", command, *arguments)
    if not isinstance(result, dict) or result.get("status") != "success":
        raise DeliveryError(
            result.get("reason", "FEEDBACK_UNAVAILABLE")
            if isinstance(result, dict)
            else "FEEDBACK_UNAVAILABLE"
        )
    return result


def _round(task, root):
    metadata = _show(task).get("metadata", {})
    if not metadata.get(FEEDBACK + "workflow"):
        return None
    if metadata[FEEDBACK + "workflow"] != root:
        raise DeliveryError("ROUND_MISMATCH")
    return _feedback(
        "show", "--task", task, "--workflow", root, "--round", str(metadata[FEEDBACK + "round"])
    )


def _begin_round(task, root, job):
    metadata = _show(task).get("metadata", {})
    branch = git(job["project"], "branch", "--show-current")
    if not branch or (job.get("github") and job["github"]["head"] != branch):
        raise DeliveryError("BRANCH_MISMATCH")
    if metadata.get(FEEDBACK + "workflow"):
        bound = _show(root).get("metadata", {})
        if (
            metadata[FEEDBACK + "workflow"] != root
            or bound.get(FEEDBACK + "task") != task
            or str(bound.get(FEEDBACK + "round")) != str(metadata.get(FEEDBACK + "round"))
        ):
            raise DeliveryError("ROUND_MISMATCH")
        if metadata.get(FEEDBACK + "branch") != branch:
            raise DeliveryError("BRANCH_MISMATCH")
    else:
        _feedback("begin", "--task", task, "--workflow", root, "--branch", branch)


def workflow(value):
    if value:
        return _identity(value)
    bead = _show(os.environ.get("GC_BEAD_ID", ""))
    return _identity(bead.get("metadata", {}).get("gc.root_bead_id"))


def approved(root, task):
    binary, city = os.environ.get("GC_BIN", ""), os.environ.get("GC_CITY_PATH", "")
    result = subprocess.run(
        [binary, "base", "brief", "verify", "--workflow", root, "--task", task],
        cwd=city,
        env=environment(),
        capture_output=True,
        timeout=60,
    )
    if result.returncode or len(result.stdout) > 100_000:
        raise DeliveryError("BRIEF_PENDING_APPROVAL")
    reference = json.loads(result.stdout)
    if reference.get("status") != "success" or reference.get("task_id") != task:
        raise DeliveryError("BRIEF_PENDING_APPROVAL")
    return reference


class Delivery:
    """Native workflow and publication with a stack adapter providing validate and run."""

    def __init__(self, checks):
        self.checks = checks

    def bind(self, args):
        if "DEVKIT_UNATTENDED" in os.environ:
            raise DeliveryError("OPERATOR_CONFIGURATION_REQUIRED")
        root = _show(args.workflow)
        _show(args.task)
        _selection(args.workflow, args.task)
        job, _ = load(args.file)
        self.checks.validate(job)
        _begin_round(args.task, args.workflow, job)
        state = Path(os.environ.get("GC_PACK_STATE_DIR", ""))
        if not state.is_absolute():
            raise DeliveryError("TASK_STATE_UNAVAILABLE")
        path = state / "jobs" / (_identity(args.workflow) + ".json")
        content = {"task": args.task, "workflow": args.workflow, "job": job}
        if path.exists():
            if load(path)[0] != content:
                raise DeliveryError("JOB_ALREADY_BOUND")
        else:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            save(path, content)
        _, digest = load(path)
        old = root.get("metadata", {}).get(PREFIX + "sha256")
        if old is not None and old != digest:
            raise DeliveryError("JOB_ALREADY_BOUND")
        _update(args.workflow, {PREFIX + "job": str(path), PREFIX + "sha256": digest})
        return {"status": "success", "workflow": args.workflow, "path": str(path), "sha256": digest}

    def selected(self, root):
        metadata = _show(root).get("metadata", {})
        if PREFIX + "job" not in metadata:
            raise DeliveryError("JOB_NOT_BOUND")
        content, digest = load(metadata[PREFIX + "job"])
        if digest != metadata.get(PREFIX + "sha256") or content.get("workflow") != root:
            raise DeliveryError("JOB_HASH_MISMATCH")
        self.checks.validate(content["job"])
        return content

    def check(self, args):
        root = workflow(args.workflow)
        content = self.selected(root)
        reference = approved(root, content["task"])
        result = self.checks.run(content["job"], reference)
        _update(root, {PREFIX + "checks": str(Path(result["directory"]) / "results.json")})
        return result

    def report(self, args):
        root = workflow(args.workflow)
        content = self.selected(root)
        reference = approved(root, content["task"])
        metadata = _show(root).get("metadata", {})
        path = metadata.get(PREFIX + "checks")
        if not isinstance(path, str):
            raise DeliveryError("CHECKS_NOT_PASSED")
        artifact = Path(path)
        if (
            artifact.parent.parent != Path(content["job"]["artifacts"])
            or artifact.name != "results.json"
        ):
            raise DeliveryError("CHECKS_NOT_PASSED")
        bundle, _ = load(path, 1_000_000)
        brief, digest, _ = load_brief(reference["path"], content["task"])
        if digest != reference["sha256"]:
            raise DeliveryError("BRIEF_HASH_MISMATCH")
        return prepare(
            content["job"], reference, bundle, brief, feedback=_round(content["task"], root)
        )

    def publication(self, args):
        root = workflow(args.workflow)
        members = _members(root)
        implementations = [
            node
            for node in members
            if node.get("metadata", {}).get("gc.step_ref", "").split(".")[-1] == "implement"
        ]
        drafts = [
            node
            for node in members
            if node.get("metadata", {}).get("devkit.delivery.role") == "draft"
        ]
        if (
            len(implementations) != 1
            or implementations[0]["status"] != "closed"
            or implementations[0].get("metadata", {}).get("gc.outcome") != "pass"
            or len(drafts) != 1
        ):
            raise DeliveryError("NATIVE_CHECK_PENDING")
        content = self.selected(root)
        state = _round(content["task"], root)
        known = (state or {}).get("pr") or _show(root).get("metadata", {}).get(PREFIX + "pr")
        result = publish(
            content["job"], self.report(args), args.approved_body_sha256, known_pr=known
        )
        _update(root, {PREFIX + "pr": result["url"]})
        if state is not None:
            _feedback(
                "link-pr",
                "--task",
                content["task"],
                "--workflow",
                root,
                "--round",
                str(state["round"]),
                "--pr",
                result["url"],
            )
        if drafts[0]["status"] != "closed":
            _gc("close", drafts[0]["id"], "--reason", "Confirmed checked draft " + result["url"])
        return result


def main(checks):
    delivery = Delivery(checks)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    configure = commands.add_parser("bind", help="Bind reviewed operator job inputs once")
    configure.add_argument("file")
    configure.add_argument("--workflow", required=True)
    configure.add_argument("--task", required=True)
    configure.set_defaults(handler=delivery.bind)
    checks = commands.add_parser("check", help="Run gates for the approved clean commit")
    checks.add_argument("--workflow")
    checks.set_defaults(handler=delivery.check)
    text = commands.add_parser("report", help="Prepare the exact checked draft text for review")
    text.add_argument("--workflow", required=True)
    text.set_defaults(handler=delivery.report)
    submit = commands.add_parser("publish", help="Operator publication of an approved draft body")
    submit.add_argument("--workflow", required=True)
    submit.add_argument("--approved-body-sha256", required=True)
    submit.set_defaults(handler=delivery.publication)
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except (DeliveryError, BriefError, StateError) as error:
        result = {"status": "blocked", "reason": error.reason}
    except (OSError, ValueError, TypeError, KeyError, RecursionError, subprocess.SubprocessError):
        result = {"status": "blocked", "reason": "DELIVERY_INPUT_UNAVAILABLE"}
    print(json.dumps(result))
    # Native exec checks distinguish semantic red from infrastructure retry (75).
    return {"success": 0, "failed": 1, "blocked": 75}[result["status"]]
