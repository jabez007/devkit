"""A new native workflow needs its own approval while retaining delivery identity."""

import json
import os
from pathlib import Path

import pytest

from tests.test_gascity_brief_approval import command as brief_command
from tests.test_gascity_brief_approval import workflow as workflow
from tests.test_gascity_feedback import QUESTION, invoke
from tests.test_gascity_feedback import feedback as feedback


@pytest.fixture
def round_trip(request):
    state = request.getfixturevalue("feedback")
    values = json.loads(state.read_text())
    sha = values["run-one"]["metadata"]["devkit.brief.sha256"]
    assert brief_command("approve", "--workflow", "run-one", "--sha256", sha)[0] == 0
    values = json.loads(state.read_text())
    values.update(
        {
            "implement-one": dict(
                id="implement-one",
                status="closed",
                metadata={"gc.root_bead_id": "run-one", "gc.step_ref": "brief.implement"},
            ),
            "run-two": dict(id="run-two", status="open", metadata={}),
            "approve-two": dict(
                id="approve-two",
                status="open",
                metadata={
                    "gc.root_bead_id": "run-two",
                    "gc.step_ref": "brief.approve",
                    "devkit.brief.role": "approval",
                    "devkit.task": "task-one",
                },
            ),
            "gate-two": dict(
                id="gate-two",
                status="open",
                metadata={
                    "gc.root_bead_id": "run-two",
                    "gc.step_ref": "brief.gate-approve",
                    "gc.gate_type": "human",
                },
            ),
        }
    )
    state.write_text(json.dumps(values))
    code, linked = invoke(state, "link-pr", pr="https://github.com/fixture/repo/pull/1")
    assert code == 0, linked
    return state


def reject_assumption(state):
    _, question = invoke(state, "questions", [QUESTION])
    code, answer = invoke(
        state,
        "answers",
        [
            dict(
                question_id=question["ids"][0],
                accepted=False,
                answer="Call the menu Dispatch contacts.",
            )
        ],
    )
    assert code == 0, answer


def proposal(state):
    path = state.with_name("round-two-brief.json")
    # Draft takes an output path rather than the input-array convenience in invoke.
    from tests.test_gascity_feedback import command

    code, result = command(
        "draft", path, "--task", "task-one", "--workflow", "run-one", "--round", "1"
    )
    return path, code, result


def advance(state, path, next_workflow="run-two"):
    from tests.test_gascity_feedback import command

    return command(
        "next",
        path,
        "--task",
        "task-one",
        "--workflow",
        "run-one",
        "--round",
        "1",
        "--next-workflow",
        next_workflow,
    )


def test_rejected_assumption_becomes_a_reviewable_behavior_brief(round_trip):
    reject_assumption(round_trip)
    path, code, result = proposal(round_trip)
    assert code == 0 and result["next_round"] == 2, result
    data = json.loads(path.read_text())
    assert data["task_id"] == "task-one"
    assert "Call the menu Dispatch contacts." in data["acceptance_criteria"]
    assert result["branch"] == "devkit/task-one"
    assert result["pr"] == "https://github.com/fixture/repo/pull/1"
    assert (
        json.loads(round_trip.read_text())["task-one"]["metadata"]["devkit.feedback.round"] == "1"
    )


def test_round_two_reuses_identity_and_cannot_inherit_round_one_approval(round_trip):
    reject_assumption(round_trip)
    path, _, _ = proposal(round_trip)
    assert brief_command("resume", "--task", "task-one")[0] == 0
    code, advanced = advance(round_trip, path)
    assert code == 0 and advanced["round"] == 2
    assert advanced["workflow"] == "run-two"
    assert advanced["branch"] == "devkit/task-one"
    assert advanced["pr"] == "https://github.com/fixture/repo/pull/1"
    code, blocked = brief_command("resume", "--task", "task-one")
    assert code == 2 and blocked["reason"] == "BRIEF_PENDING_APPROVAL"
    approved = brief_command(
        "approve", "--workflow", "run-two", "--sha256", advanced["brief_sha256"]
    )
    assert approved[0] == 0, approved
    resumed = brief_command("resume", "--task", "task-one")
    assert resumed[0] == 0 and resumed[1]["workflow"] == "run-two"


def test_repeated_advance_keeps_the_same_round_and_artifact(round_trip):
    reject_assumption(round_trip)
    path, _, _ = proposal(round_trip)
    first = advance(round_trip, path)
    second = advance(round_trip, path)
    assert first == second and second[1]["round"] == 2
    references = json.loads(round_trip.read_text())["run-two"]["metadata"]
    assert references["devkit.feedback.previous_workflow"] == "run-one"
    assert len(references["devkit.feedback.answers_sha256"]) == 64


def test_all_questions_need_answers_before_a_new_round(round_trip):
    invoke(round_trip, "questions", [QUESTION])
    _, code, result = proposal(round_trip)
    assert (code, result["reason"]) == (2, "ANSWERS_PENDING")


def test_accepted_assumptions_do_not_require_a_new_brief(round_trip):
    _, question = invoke(round_trip, "questions", [QUESTION])
    invoke(round_trip, "answers", [dict(question_id=question["ids"][0], accepted=True)])
    _, code, result = proposal(round_trip)
    assert (code, result["reason"]) == (2, "NO_REJECTED_ASSUMPTIONS")


def test_reusing_the_previous_workflow_is_refused(round_trip):
    reject_assumption(round_trip)
    path, _, _ = proposal(round_trip)
    code, result = advance(round_trip, path, "run-one")
    assert (code, result["reason"]) == (2, "FRESH_WORKFLOW_REQUIRED")


def test_unchanged_semantics_are_not_a_new_brief(round_trip):
    reject_assumption(round_trip)
    source = round_trip.with_name("brief.json")
    code, result = advance(round_trip, source)
    assert (code, result["reason"]) == (2, "NEW_BRIEF_REQUIRED")


def test_a_gate_closed_before_round_binding_is_refused(round_trip):
    reject_assumption(round_trip)
    path, _, _ = proposal(round_trip)
    saved = brief_command("record", str(path), "--task", "task-one", "--workflow", "run-two")
    assert saved[0] == 0
    assert brief_command("approve", "--workflow", "run-two", "--sha256", saved[1]["sha256"])[0] == 0
    code, result = advance(round_trip, path)
    assert (code, result["reason"]) == (2, "FRESH_APPROVAL_REQUIRED")


def test_partial_round_transition_retries_the_same_native_workflow(round_trip, monkeypatch):
    reject_assumption(round_trip)
    path, _, _ = proposal(round_trip)
    gc = Path(os.environ["GC_BIN"])
    source = gc.read_text().replace(
        "elif command == 'update':\n    identity = args.pop(0)",
        "elif command == 'update':\n    identity = args.pop(0)\n"
        "    if os.environ.get('FAIL_ROUND_UPDATE') == identity: sys.exit(1)",
    )
    gc.write_text(source)
    monkeypatch.setenv("FAIL_ROUND_UPDATE", "task-one")
    assert advance(round_trip, path)[0] == 2
    assert (
        json.loads(round_trip.read_text())["task-one"]["metadata"]["devkit.feedback.round"] == "1"
    )
    monkeypatch.delenv("FAIL_ROUND_UPDATE")
    code, result = advance(round_trip, path)
    assert code == 0 and result["workflow"] == "run-two" and result["round"] == 2
