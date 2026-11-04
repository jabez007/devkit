"""Brief artifacts and approval references through native Beads commands."""

import os
import re
import tempfile
from pathlib import Path

from brief_format import BriefError, findings, load
from native_state import _gc, _identity, _members, _show, _update

PREFIX = "devkit.brief."
FIELDS = ("task", "path", "gate", "approval", "sha256")


def _selection(workflow, task):
    members = _members(workflow)
    approvals = [
        bead for bead in members if bead.get("metadata", {}).get(PREFIX + "role") == "approval"
    ]
    gates = [
        bead
        for bead in members
        if bead.get("metadata", {}).get("gc.gate_type") == "human"
        and bead.get("metadata", {}).get("gc.step_ref", "").split(".")[-1] == "gate-approve"
    ]
    if len(approvals) != 1 or len(gates) != 1:
        raise BriefError("BRIEF_GATE_MISMATCH")
    approval, gate = approvals[0], gates[0]
    if approval.get("metadata", {}).get("devkit.task") != task:
        raise BriefError("BRIEF_TASK_MISMATCH")
    _validate_nodes(workflow, task, approval, gate)
    return approval, gate


def _validate_nodes(workflow, task, approval, gate):
    for bead in (approval, gate):
        _identity(bead.get("id"))
        if bead.get("metadata", {}).get("gc.root_bead_id") != workflow:
            raise BriefError("BRIEF_GATE_MISMATCH")
    if (
        approval["metadata"].get(PREFIX + "role") != "approval"
        or approval["metadata"].get("devkit.task") != task
        or gate["metadata"].get("gc.gate_type") != "human"
    ):
        raise BriefError("BRIEF_GATE_MISMATCH")


def _artifact(workflow, digest):
    if not isinstance(digest, str) or re.fullmatch("[0-9a-f]{64}", digest) is None:
        raise BriefError("INVALID_TASK_STATE")
    state = Path(os.environ.get("GC_PACK_STATE_DIR", ""))
    if not state.is_absolute():
        raise BriefError("TASK_STATE_UNAVAILABLE")
    return state.resolve() / "briefs" / _identity(workflow) / (digest + ".json")


def _save(path, content):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.chmod(0o400)
        try:
            # Publish the complete artifact without ever replacing an existing revision.
            os.link(temporary, path)
        except FileExistsError:
            _, _, existing = load(path)
            if existing != content:
                raise BriefError("BRIEF_HASH_MISMATCH") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def record(args):
    brief, digest, content = load(args.file, args.task)
    if findings(brief):
        raise BriefError("PRESCRIPTIVE_BRIEF")
    _show(args.task)
    root = _show(args.workflow)
    metadata = root.get("metadata", {})
    if previous := metadata.get(PREFIX + "sha256"):
        if previous != digest:
            raise BriefError("BRIEF_REVISION_REQUIRES_NEW_WORKFLOW")
        return _reference(args.workflow, args.task)[0]
    approval, gate = _selection(args.workflow, args.task)
    if gate["status"] == "closed" or approval["status"] == "closed":
        raise BriefError("BRIEF_GATE_MISMATCH")
    path = _artifact(args.workflow, digest)
    _save(path, content)
    reference = dict(
        task=args.task, path=str(path), gate=gate["id"], approval=approval["id"], sha256=digest
    )
    _update(args.workflow, {PREFIX + key: value for key, value in reference.items()})
    return {
        "status": "success",
        "workflow": args.workflow,
        "task_id": args.task,
        "sha256": digest,
        "path": str(path),
    }


def _reference(workflow, task=None):
    metadata = _show(workflow).get("metadata", {})
    if not all(isinstance(metadata.get(PREFIX + field), str) for field in FIELDS):
        raise BriefError("BRIEF_NOT_RECORDED")
    reference = {key: metadata[PREFIX + key] for key in FIELDS}
    selected = _identity(reference["task"])
    if task is not None and selected != task:
        raise BriefError("BRIEF_TASK_MISMATCH")
    path = _artifact(workflow, reference["sha256"])
    if reference["path"] != str(path):
        raise BriefError("BRIEF_RECORD_MISMATCH")
    brief, digest, _ = load(path, selected)
    if digest != reference["sha256"]:
        raise BriefError("BRIEF_HASH_MISMATCH")
    if findings(brief):
        raise BriefError("PRESCRIPTIVE_BRIEF")
    approval, gate = _show(reference["approval"]), _show(reference["gate"])
    _validate_nodes(workflow, selected, approval, gate)
    result = {
        "status": "success",
        "workflow": workflow,
        "task_id": selected,
        "sha256": digest,
        "path": str(path),
    }
    return result, brief, approval, gate


def show(args):
    result, brief, _, gate = _reference(args.workflow)
    return {**result, "brief": brief, "gate_status": gate["status"]}


def approve(args):
    if "DEVKIT_UNATTENDED" in os.environ:
        raise BriefError("HUMAN_APPROVAL_REQUIRED")
    result, _, approval, gate = _reference(args.workflow)
    if args.sha256 != result["sha256"]:
        raise BriefError("BRIEF_HASH_MISMATCH")
    _update(
        gate["id"],
        {PREFIX + "approved_sha256": result["sha256"], PREFIX + "approved_task": result["task_id"]},
    )
    for bead in (gate, approval):
        if bead["status"] != "closed":
            _gc("close", bead["id"], "--reason", "Approved behavior brief " + result["sha256"])
    return result


def verify(args):
    result, _, approval, gate = _reference(args.workflow, args.task)
    metadata = gate.get("metadata", {})
    if (
        gate["status"] != "closed"
        or approval["status"] != "closed"
        or metadata.get(PREFIX + "approved_sha256") != result["sha256"]
        or metadata.get(PREFIX + "approved_task") != result["task_id"]
    ):
        raise BriefError("BRIEF_PENDING_APPROVAL")
    return result


def resume(args):
    task = _identity(args.task)
    metadata = _show(task).get("metadata", {})
    if active := metadata.get("devkit.feedback.workflow"):
        args.workflow = _identity(active)
        number = str(metadata.get("devkit.feedback.round"))
        root = _show(args.workflow).get("metadata", {})
        if (
            not number.isdigit()
            or not 1 <= int(number) <= 10000
            or str(root.get("devkit.feedback.round")) != number
            or root.get("devkit.feedback.task") != task
        ):
            raise BriefError("ROUND_MISMATCH")
        return verify(args)
    roots = _gc(
        "list",
        "--all",
        "--include-ephemeral",
        "--limit",
        "256",
        "--metadata-field",
        PREFIX + "task=" + task,
    )
    if not isinstance(roots, list):
        raise BriefError("INVALID_TASK_STATE")
    if not roots:
        raise BriefError("BRIEF_NOT_RECORDED")
    if len(roots) != 1:
        raise BriefError("BRIEF_RESUME_AMBIGUOUS")
    args.workflow = _identity(roots[0].get("id"))
    return verify(args)
