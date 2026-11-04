"""Round identity and structured feedback through native Beads task comments."""

import hashlib
import json
import os
import re

from brief_format import _read
from brief_state import _reference
from native_state import StateError, _gc, _identity, _show, _update

PREFIX = "devkit.feedback."
MARKER = "devkit-feedback:v1\n"
FIELDS = {
    "question": {"question", "assumption", "reason"},
    "friction": {"command", "expected", "observed", "action"},
}


def _human():
    if "DEVKIT_UNATTENDED" in os.environ:
        raise StateError("HUMAN_FEEDBACK_REQUIRED")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StateError("INVALID_FEEDBACK")
        result[key] = value
    return result


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _load(path):
    value = json.loads(_read(path), object_pairs_hook=_object)
    if not isinstance(value, list) or len(value) > 100:
        raise StateError("INVALID_FEEDBACK")
    return value


def begin(args):
    _human()
    _reference(args.workflow, args.task)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,255}", args.branch):
        raise StateError("INVALID_BRANCH")
    if args.pr and not re.fullmatch(
        r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*", args.pr
    ):
        raise StateError("INVALID_PR")
    fields = {"round": "1", "workflow": args.workflow, "branch": args.branch}
    if args.pr:
        fields["pr"] = args.pr
    previous = _show(args.task).get("metadata", {})
    if PREFIX + "round" in previous and any(
        str(previous.get(PREFIX + key)) != value for key, value in fields.items()
    ):
        raise StateError("TASK_ROUND_ALREADY_STARTED")
    _update(args.workflow, {PREFIX + "round": "1", PREFIX + "task": args.task})
    _update(args.task, {PREFIX + key: value for key, value in fields.items()})
    return {"status": "success", **current(args.task)}


def current(task, workflow=None, number=None):
    metadata = _show(task).get("metadata", {})
    try:
        raw_round = metadata[PREFIX + "round"]
        if type(raw_round) not in {str, int}:
            raise ValueError("Round numbers must be integers")
        round_number = int(raw_round)
        active = _identity(metadata[PREFIX + "workflow"])
        branch = metadata[PREFIX + "branch"]
    except (KeyError, ValueError, TypeError) as error:
        raise StateError("NO_ACTIVE_ROUND") from error
    if not 1 <= round_number <= 10000 or not isinstance(branch, str):
        raise StateError("INVALID_TASK_STATE")
    if (workflow is not None and workflow != active) or (
        number is not None and number != round_number
    ):
        raise StateError("ROUND_MISMATCH")
    reference = _reference(active, task)[0]
    root = _show(active).get("metadata", {})
    if str(root.get(PREFIX + "round")) != str(round_number) or root.get(PREFIX + "task") != task:
        raise StateError("ROUND_MISMATCH")
    return dict(
        task=task,
        workflow=active,
        round=round_number,
        branch=branch,
        pr=metadata.get(PREFIX + "pr"),
        brief_sha256=reference["sha256"],
    )


def _entries(path, kind):
    entries = _load(path)
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != FIELDS[kind]:
            raise StateError("INVALID_FEEDBACK")
        for key, value in entry.items():
            if not isinstance(value, str) or len(value) > 16000:
                raise StateError("INVALID_FEEDBACK")
            if key != "observed" and not value.strip():
                raise StateError("INVALID_FEEDBACK")
    return entries


def comments(task):
    values = _gc("comments", _identity(task))
    if not isinstance(values, list):
        raise StateError("INVALID_TASK_STATE")
    records = []
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise StateError("INVALID_TASK_STATE")
        if item["text"].startswith(MARKER):
            event = json.loads(item["text"][len(MARKER) :], object_pairs_hook=_object)
            if not isinstance(event, dict) or event.get("schema_version") != 1:
                raise StateError("INVALID_FEEDBACK_COMMENT")
            if not isinstance(event.get("id"), str):
                raise StateError("INVALID_FEEDBACK_COMMENT")
            records.append(event)
    return records


def _event(kind, context, content):
    event = {
        "schema_version": 1,
        "kind": kind,
        "task": context["task"],
        "workflow": context["workflow"],
        "round": context["round"],
        **content,
    }
    # Branch and PR publication can change without changing a round's question identity.
    return {**event, "id": _digest(content if kind == "friction" else event)}


def _append(task, events):
    existing = {event["id"] for event in comments(task)}
    added = 0
    for event in events:
        if event["id"] in existing:
            continue
        _gc(
            "comments",
            "add",
            task,
            MARKER + json.dumps(event, ensure_ascii=True, sort_keys=True),
            "--author",
            "Devkit feedback",
        )
        existing.add(event["id"])
        added += 1
    return {"status": "success", "recorded": added, "ids": [event["id"] for event in events]}


def questions(args):
    context = current(args.task, args.workflow, args.round)
    events = [_event("question", context, value) for value in _entries(args.file, "question")]
    return _append(args.task, events)


def _round_records(context):
    return [
        event
        for event in comments(context["task"])
        if event.get("workflow") == context["workflow"] and event.get("round") == context["round"]
    ]


def _answers(entries, known):
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or not {"question_id", "accepted"} <= set(entry) <= {
            "question_id",
            "accepted",
            "answer",
        }:
            raise StateError("INVALID_ANSWER")
        if entry["question_id"] not in known or type(entry["accepted"]) is not bool:
            raise StateError("UNKNOWN_QUESTION")
        text = entry.get("answer", "")
        if (
            not isinstance(text, str)
            or len(text) > 16000
            or (not entry["accepted"] and not text.strip())
        ):
            raise StateError("INVALID_ANSWER")
        result.append({**entry, "answer": text})
    if len({item["question_id"] for item in result}) != len(result):
        raise StateError("DUPLICATE_ANSWER")
    return result


def answers(args):
    _human()
    context = current(args.task, args.workflow, args.round)
    records = _round_records(context)
    known = {event["id"] for event in records if event.get("kind") == "question"}
    previous = {event["question_id"]: event for event in records if event.get("kind") == "answer"}
    events = [_event("answer", context, value) for value in _answers(_load(args.file), known)]
    for event in events:
        old = previous.get(event["question_id"])
        if old is not None and old["id"] != event["id"]:
            raise StateError("ANSWER_ALREADY_RECORDED")
    return _append(args.task, events)


def friction(args):
    context = current(args.task, args.workflow, args.round)
    entries = _entries(args.file, "friction")
    if not entries:
        return {"status": "success", "recorded": 0, "ids": []}
    if not args.friction_task or args.friction_task == args.task:
        raise StateError("SEPARATE_FRICTION_TASK_REQUIRED")
    _show(args.friction_task)
    return _append(args.friction_task, [_event("friction", context, value) for value in entries])


def show(args):
    context = current(args.task, args.workflow, args.round)
    records = _round_records(context)
    return {
        "status": "success",
        **context,
        "questions": [item for item in records if item.get("kind") == "question"],
        "answers": [item for item in records if item.get("kind") == "answer"],
    }
