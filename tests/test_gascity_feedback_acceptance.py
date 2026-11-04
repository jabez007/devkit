"""Opt-in feedback records through real native Gas City and Beads commands."""

import json
import os
import subprocess

import pytest

from tests.test_gascity_odoo_acceptance import city as city

pytestmark = pytest.mark.skipif(
    os.environ.get("DEVKIT_GASCITY_ACCEPTANCE") != "1",
    reason="Set DEVKIT_GASCITY_ACCEPTANCE=1 and the pinned native tool paths",
)


def feedback_command(workspace, *arguments):
    return workspace.run(workspace.args.gc, "base", "feedback", *arguments, structured=True)


def test_native_questions_answers_and_separate_friction_import_once(request):
    workspace = request.getfixturevalue("city")
    task = workspace.gc(
        "bd", "create", "Synthetic feedback task", "--type", "task", "--json", structured=True
    )["id"]
    tooling = workspace.gc(
        "bd", "create", "Synthetic tool friction", "--type", "task", "--json", structured=True
    )["id"]
    brief = workspace.root / "brief.json"
    brief.write_text(
        json.dumps(
            dict(
                schema_version=1,
                task_id=task,
                problem="The menu label is unclear.",
                acceptance_criteria=["The menu clearly identifies delivery contacts."],
                approach="Use a recognizable label.",
                scope=dict(in_scope=["Delivery menu"], out_of_scope=["Other applications"]),
                open_questions=[],
            )
        )
    )
    cooked = workspace.gc(
        "formula",
        "cook",
        "devkit-approved-brief",
        "--attach",
        task,
        "--var",
        "task=" + task,
        "--var",
        "brief_file=" + str(brief),
        "--json",
        structured=True,
    )
    root = cooked["root_id"]
    workspace.run(
        workspace.args.gc,
        "base",
        "brief",
        "record",
        brief,
        "--task",
        task,
        "--workflow",
        root,
        structured=True,
    )
    started = feedback_command(
        workspace, "begin", "--task", task, "--workflow", root, "--branch", "devkit/" + task
    )
    assert started["round"] == 1
    assert (
        feedback_command(
            workspace, "begin", "--task", task, "--workflow", root, "--branch", "devkit/" + task
        )["round"]
        == 1
    )
    selection = ["--task", task, "--workflow", root, "--round", "1"]
    questions = workspace.root / "questions.json"
    questions.write_text(
        json.dumps(
            [
                dict(
                    question="What should the menu be called?",
                    assumption="Use Delivery.",
                    reason="That is the existing label.",
                )
            ]
        )
    )
    first = feedback_command(workspace, "questions", questions, *selection)
    assert first["recorded"] == 1
    assert feedback_command(workspace, "questions", questions, *selection)["recorded"] == 0
    answers = workspace.root / "answers.json"
    answers.write_text(
        json.dumps(
            [
                dict(
                    question_id=first["ids"][0],
                    accepted=False,
                    answer="Call the menu Dispatch contacts.",
                )
            ]
        )
    )
    denied = subprocess.run(
        [str(workspace.args.gc), "base", "feedback", "answers", str(answers), *selection],
        cwd=workspace.city,
        env={**workspace.env, "DEVKIT_UNATTENDED": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert (
        denied.returncode == 2 and json.loads(denied.stdout)["reason"] == "HUMAN_FEEDBACK_REQUIRED"
    )
    assert feedback_command(workspace, "answers", answers, *selection)["recorded"] == 1
    assert feedback_command(workspace, "answers", answers, *selection)["recorded"] == 0
    friction = workspace.root / "friction.json"
    quote = "checker: command not found\n"
    friction.write_text(
        json.dumps(
            [
                dict(
                    command="checker --verify",
                    expected="A check result.",
                    observed=quote,
                    action="Used the installed checker path.",
                )
            ]
        )
    )
    assert (
        feedback_command(workspace, "friction", friction, *selection, "--friction-task", tooling)[
            "recorded"
        ]
        == 1
    )
    assert (
        feedback_command(workspace, "friction", friction, *selection, "--friction-task", tooling)[
            "recorded"
        ]
        == 0
    )
    task_comments = workspace.gc("bd", "comments", task, "--json", structured=True)
    tool_comments = workspace.gc("bd", "comments", tooling, "--json", structured=True)
    assert len(task_comments) == 2 and len(tool_comments) == 1
    event = json.loads(tool_comments[0]["text"].split("\n", 1)[1])
    assert event["observed"] == quote and event["task"] == task
    report = feedback_command(workspace, "show", *selection)
    assert len(report["questions"]) == 1 and len(report["answers"]) == 1
    assert report["answers"][0]["accepted"] is False
