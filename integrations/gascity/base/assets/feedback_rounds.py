"""Derive the next behavior brief and bind it to a fresh native approval gate."""

import hashlib
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

from brief_format import MAX_BYTES, BriefError, _read, findings, load
from brief_state import _reference, _selection, record, verify
from feedback_state import PREFIX, _digest, _human, _round_records, current
from native_state import StateError, _members, _show, _update


def _pr(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*", value
    ):
        raise StateError("INVALID_PR")
    return value


def link_pr(args):
    _human()
    context = current(args.task, args.workflow, args.round)
    url = _pr(args.pr)
    if context["pr"] is not None and context["pr"] != url:
        raise StateError("PR_ALREADY_BOUND")
    _update(args.workflow, {PREFIX + "pr": url})
    _update(args.task, {PREFIX + "pr": url})
    return {"status": "success", **current(args.task)}


def _answered(context):
    records = _round_records(context)
    questions = {item["id"]: item for item in records if item.get("kind") == "question"}
    answers = {item["question_id"]: item for item in records if item.get("kind") == "answer"}
    if set(questions) - set(answers):
        raise StateError("ANSWERS_PENDING")
    rejected = [answers[key] for key in sorted(questions) if not answers[key]["accepted"]]
    if not rejected:
        raise StateError("NO_REJECTED_ASSUMPTIONS")
    return questions, rejected, _digest([answers[key] for key in sorted(answers)])


def _previous(context):
    verify(SimpleNamespace(workflow=context["workflow"], task=context["task"]))
    if context["pr"] is None:
        raise StateError("PR_REQUIRED_FOR_NEXT_ROUND")
    implementations = [
        node
        for node in _members(context["workflow"])
        if node.get("metadata", {}).get("gc.step_ref", "").split(".")[-1] == "implement"
    ]
    if len(implementations) != 1 or implementations[0]["status"] != "closed":
        raise StateError("PREVIOUS_ROUND_INCOMPLETE")


def draft(args):
    _human()
    context = current(args.task, args.workflow, args.round)
    if context["round"] >= 10000:
        raise StateError("ROUND_LIMIT")
    _previous(context)
    questions, rejected, digest = _answered(context)
    original = _reference(args.workflow, args.task)[1]
    proposal = {
        **original,
        "acceptance_criteria": list(
            dict.fromkeys(
                [*original["acceptance_criteria"], *[item["answer"] for item in rejected]]
            )
        ),
        "open_questions": [
            text
            for text in original.get("open_questions", [])
            if text not in {item["question"] for item in questions.values()}
        ],
    }
    if findings(proposal):
        raise BriefError("PRESCRIPTIVE_ANSWER_REQUIRES_REVIEWED_BRIEF")
    raw = json.dumps(proposal, ensure_ascii=True, indent=2).encode() + b"\n"
    if len(raw) > MAX_BYTES:
        raise BriefError("BRIEF_LIMIT")
    path = Path(args.file).absolute()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        if _read(path) != raw:
            raise StateError("DRAFT_ALREADY_EXISTS")
    else:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
    return {
        "status": "success",
        "task": args.task,
        "next_round": args.round + 1,
        "file": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "answers_sha256": digest,
        "branch": context["branch"],
        "pr": context["pr"],
    }


def _repeated(args, context):
    metadata = _show(args.next_workflow).get("metadata", {})
    if (
        context["round"] != args.round + 1
        or context["workflow"] != args.next_workflow
        or metadata.get(PREFIX + "previous_workflow") != args.workflow
    ):
        raise StateError("ROUND_MISMATCH")
    _, digest, _ = load(args.file, args.task)
    if digest != context["brief_sha256"]:
        raise StateError("ROUND_BRIEF_MISMATCH")
    return {"status": "success", **context}


def next_round(args):
    _human()
    context = current(args.task)
    if context["round"] != args.round or context["workflow"] != args.workflow:
        return _repeated(args, context)
    if context["round"] >= 10000:
        raise StateError("ROUND_LIMIT")
    _previous(context)
    _, _, digest = _answered(context)
    if args.next_workflow == args.workflow:
        raise StateError("FRESH_WORKFLOW_REQUIRED")
    proposal, _, _ = load(args.file, args.task)
    if proposal == _reference(args.workflow, args.task)[1]:
        raise StateError("NEW_BRIEF_REQUIRED")
    approval, gate = _selection(args.next_workflow, args.task)
    if approval["status"] == "closed" or gate["status"] == "closed":
        raise StateError("FRESH_APPROVAL_REQUIRED")
    record(SimpleNamespace(file=args.file, workflow=args.next_workflow, task=args.task))
    number = str(args.round + 1)
    _update(
        args.next_workflow,
        {
            PREFIX + "round": number,
            PREFIX + "task": args.task,
            PREFIX + "branch": context["branch"],
            PREFIX + "pr": context["pr"],
            PREFIX + "previous_workflow": args.workflow,
            PREFIX + "answers_sha256": digest,
        },
    )
    _update(args.task, {PREFIX + "round": number, PREFIX + "workflow": args.next_workflow})
    return {"status": "success", **current(args.task)}
