"""Feedback command behavior through a native-command adapter and immutable brief artifacts."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_gascity_brief_approval import record
from tests.test_gascity_brief_approval import workflow as workflow

BASE = Path(__file__).resolve().parents[1] / "integrations/gascity/base"
COMMENT_COMMAND = r"""
if command == 'comments':
    comments_path = path.with_suffix('.comments')
    comments = json.loads(comments_path.read_text()) if comments_path.exists() else {}
    if args[0] == 'add':
        task, content = args[1:3]
        items = comments.setdefault(task, [])
        value = dict(id='comment-' + str(len(items) + 1), issue_id=task,
                     text=content, author=args[args.index('--author') + 1])
        items.append(value)
        comments_path.write_text(json.dumps(comments))
        print(json.dumps(value))
    else:
        print(json.dumps(comments.get(args[0], [])))
"""


def command(*arguments):
    process = subprocess.run(
        [sys.executable, str(BASE / "assets/feedback.py"), *map(str, arguments)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.stdout.strip(), process.stderr
    return process.returncode, json.loads(process.stdout)


@pytest.fixture
def feedback(request):
    brief, state = request.getfixturevalue("workflow")
    gc = Path(os.environ["GC_BIN"])
    gc.write_text(
        gc.read_text().replace(
            "if command == 'show':", COMMENT_COMMAND + "\nelif command == 'show':"
        )
    )
    values = json.loads(state.read_text())
    values["tooling"] = dict(id="tooling", status="open", metadata={})
    state.write_text(json.dumps(values))
    record((brief, state))
    code, result = command(
        "begin", "--task", "task-one", "--workflow", "run-one", "--branch", "devkit/task-one"
    )
    assert code == 0, result
    return state


def invoke(feedback, operation, entries=None, **flags):
    arguments = [operation]
    if entries is not None:
        path = feedback.with_name(operation + ".json")
        path.write_text(json.dumps(entries))
        arguments.append(str(path))
    for key, value in {"task": "task-one", "workflow": "run-one", "round": 1, **flags}.items():
        arguments.extend(["--" + key.replace("_", "-"), str(value)])
    return command(*arguments)


QUESTION = dict(
    question="What should the menu be called?",
    assumption="Use Delivery.",
    reason="That is the existing label.",
)
FRICTION = dict(
    command="tool --check",
    expected="The checker prints its result.",
    observed="command not found\n",
    action="Used the installed executable's absolute path.",
)


def stored(feedback, task):
    path = feedback.with_suffix(".comments")
    return json.loads(path.read_text()).get(task, []) if path.exists() else []


def test_begin_binds_task_round_and_preserves_idempotent_resume(feedback):
    code, result = command(
        "begin", "--task", "task-one", "--workflow", "run-one", "--branch", "devkit/task-one"
    )
    assert code == 0 and result["round"] == 1
    values = json.loads(feedback.read_text())
    assert values["task-one"]["metadata"]["devkit.feedback.workflow"] == "run-one"
    assert values["run-one"]["metadata"]["devkit.feedback.task"] == "task-one"


def test_begin_cannot_replace_an_active_branch(feedback):
    code, result = command(
        "begin", "--task", "task-one", "--workflow", "run-one", "--branch", "different"
    )
    assert (code, result["reason"]) == (2, "TASK_ROUND_ALREADY_STARTED")


def test_unattended_questions_keep_assumption_reason_and_round_once(feedback, monkeypatch):
    monkeypatch.setenv("DEVKIT_UNATTENDED", "1")
    code, first = invoke(feedback, "questions", [QUESTION, QUESTION])
    assert code == 0 and first["recorded"] == 1
    code, repeated = invoke(feedback, "questions", [QUESTION])
    assert code == 0 and repeated["recorded"] == 0
    code, result = invoke(feedback, "show")
    assert code == 0 and len(result["questions"]) == 1
    event = result["questions"][0]
    assert {key: event[key] for key in QUESTION} == QUESTION
    assert event["workflow"] == "run-one" and event["round"] == 1
    assert stored(feedback, "task-one")[0]["author"] == "Devkit feedback"


def test_publication_metadata_does_not_change_question_identity(feedback):
    _, first = invoke(feedback, "questions", [QUESTION])
    values = json.loads(feedback.read_text())
    values["task-one"]["metadata"]["devkit.feedback.pr"] = "https://github.com/fixture/repo/pull/1"
    feedback.write_text(json.dumps(values))
    _, second = invoke(feedback, "questions", [QUESTION])
    assert first["ids"] == second["ids"] and second["recorded"] == 0


@pytest.mark.parametrize("operation", ["begin", "answers"])
def test_unattended_session_cannot_supply_human_feedback(feedback, monkeypatch, operation):
    monkeypatch.setenv("DEVKIT_UNATTENDED", "")
    if operation == "begin":
        code, result = command(
            "begin", "--task", "task-one", "--workflow", "run-one", "--branch", "devkit/task-one"
        )
    else:
        code, result = invoke(feedback, "answers", [])
    assert (code, result["reason"]) == (2, "HUMAN_FEEDBACK_REQUIRED")
    assert not stored(feedback, "task-one")


@pytest.mark.parametrize(
    "accepted,answer", [(True, ""), (False, "Call the menu Dispatch contacts.")]
)
def test_answers_are_explicit_human_records_and_repeat_without_duplicates(
    feedback, accepted, answer
):
    _, saved = invoke(feedback, "questions", [QUESTION])
    values = [dict(question_id=saved["ids"][0], accepted=accepted, answer=answer)]
    code, result = invoke(feedback, "answers", values)
    assert code == 0 and result["recorded"] == 1
    assert invoke(feedback, "answers", values)[1]["recorded"] == 0
    state = invoke(feedback, "show")[1]
    assert state["answers"][0]["accepted"] is accepted
    assert state["answers"][0]["answer"] == answer


def test_changed_answer_needs_an_explicit_new_round(feedback):
    _, question = invoke(feedback, "questions", [QUESTION])
    answer = dict(question_id=question["ids"][0], accepted=True)
    assert invoke(feedback, "answers", [answer])[0] == 0
    code, result = invoke(
        feedback, "answers", [{**answer, "accepted": False, "answer": "Use Dispatch."}]
    )
    assert (code, result["reason"]) == (2, "ANSWER_ALREADY_RECORDED")


def test_stale_round_does_not_write_feedback(feedback):
    code, result = invoke(feedback, "questions", [QUESTION], round=2)
    assert (code, result["reason"]) == (2, "ROUND_MISMATCH")
    assert not stored(feedback, "task-one")


def test_empty_friction_is_a_normal_result_without_a_separate_task(feedback):
    assert invoke(feedback, "friction", [])[1] == dict(status="success", recorded=0, ids=[])
    assert not stored(feedback, "task-one") and not stored(feedback, "tooling")


def test_nonempty_friction_requires_a_separate_selected_task(feedback):
    code, result = invoke(feedback, "friction", [FRICTION], friction_task="task-one")
    assert (code, result["reason"]) == (2, "SEPARATE_FRICTION_TASK_REQUIRED")


def test_friction_quotes_actual_output_and_repeated_reads_record_once(feedback):
    first = invoke(feedback, "friction", [FRICTION], friction_task="tooling")[1]
    second = invoke(feedback, "friction", [FRICTION], friction_task="tooling")[1]
    assert first["recorded"] == 1 and second["recorded"] == 0
    assert first["ids"] == second["ids"]
    assert not stored(feedback, "task-one")
    events = stored(feedback, "tooling")
    assert len(events) == 1
    event = json.loads(events[0]["text"].split("\n", 1)[1])
    assert {key: event[key] for key in FRICTION} == FRICTION


def test_a_silent_tool_can_have_an_exact_empty_output_quote(feedback):
    code, result = invoke(
        feedback, "friction", [{**FRICTION, "observed": ""}], friction_task="tooling"
    )
    assert code == 0 and result["recorded"] == 1


def test_invalid_batch_writes_no_partial_comments(feedback):
    code, result = invoke(feedback, "questions", [QUESTION, {"question": "Incomplete"}])
    assert (code, result["reason"]) == (2, "INVALID_FEEDBACK")
    assert not stored(feedback, "task-one")
