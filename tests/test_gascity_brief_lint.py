"""Behavior-only brief validation through the native pack command's executable."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1] / "integrations/gascity/base"


@pytest.fixture
def brief(tmp_path):
    path = tmp_path / "brief.json"
    content = {
        "schema_version": 1,
        "task_id": "task-fixture",
        "problem": "Dispatchers cannot record a partial delivery accurately.",
        "acceptance_criteria": ["After four of ten items ship, six remain outstanding."],
        "approach": "Show the delivered and outstanding quantities separately.",
        "scope": {"in_scope": ["Partial deliveries"], "out_of_scope": ["Billing changes"]},
        "open_questions": [],
    }
    path.write_text(json.dumps(content))
    return path, content


def lint(path, *arguments):
    result = subprocess.run(
        [sys.executable, str(BASE / "assets/brief.py"), "lint", str(path), *arguments],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.stdout.strip(), result.stderr
    return result.returncode, json.loads(result.stdout)


def test_clean_brief_passes_and_identifies_exact_reviewed_bytes(brief):
    path, _ = brief
    code, result = lint(path, "--task", "task-fixture")
    assert code == 0 and result["status"] == "success", result
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["task_id"] == "task-fixture"
    assert result["findings"] == []


@pytest.mark.parametrize(
    "prescription,kind",
    [
        ("Edit addons/sale/models/order.py to store the quantity.", "file_path"),
        ("Change models\\order.py before shipping.", "file_path"),
        ("Update the res.partner model.", "dotted_name"),
        ("Call button_validate() once.", "call"),
        ("Add delivered_qty to the form.", "identifier"),
        ("Run the command with --test-enable.", "command_flag"),
        ("Use `python` to calculate the remainder.", "code"),
        ("Update package.json.", "source_file"),
    ],
)
def test_lint_flags_obvious_implementation_names_without_echoing_text(brief, prescription, kind):
    path, content = brief
    content["approach"] = prescription
    path.write_text(json.dumps(content))
    code, result = lint(path)
    assert code == 1 and result["reason"] == "PRESCRIPTIVE_BRIEF", result
    assert any(finding["kind"] == kind for finding in result["findings"])
    assert all(finding["section"] == "approach" for finding in result["findings"])
    assert prescription not in json.dumps(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("acceptance_criteria", []),
        ("problem", ""),
        ("scope", {}),
        ("schema_version", True),
        ("task_id", "bad task identity"),
        ("extra", "unrecognized"),
    ],
)
def test_lint_refuses_invalid_brief_shape(brief, field, value):
    path, content = brief
    content[field] = value
    path.write_text(json.dumps(content))
    code, result = lint(path)
    assert code == 3 and result["reason"] == "INVALID_BRIEF", result


def test_lint_rejects_task_identity_mismatch(brief):
    code, result = lint(brief[0], "--task", "another-task")
    assert code == 3 and result["reason"] == "BRIEF_TASK_MISMATCH", result


def test_lint_refuses_more_than_100_kilobytes(brief):
    brief[0].write_bytes(b"x" * 100_001)
    code, result = lint(brief[0])
    assert code == 3 and result["reason"] == "BRIEF_LIMIT", result


def test_lint_refuses_fifo_without_hanging(tmp_path):
    path = tmp_path / "brief.json"
    os.mkfifo(path)
    code, result = lint(path)
    assert code == 3 and result["reason"] == "INVALID_BRIEF", result


def test_lint_checks_questions_and_scope_as_well_as_acceptance_criteria(brief):
    path, content = brief
    content["open_questions"] = ["Should stock.move carry the quantity?"]
    content["scope"]["in_scope"] = ["Update views/delivery.xml"]
    path.write_text(json.dumps(content))
    code, result = lint(path)
    assert code == 1
    sections = {finding["section"] for finding in result["findings"]}
    assert {"open_questions[0]", "scope.in_scope[0]"} <= sections


def test_lint_uses_byte_limit_for_unicode(brief):
    path, content = brief
    content["problem"] = "界" * 34_000
    path.write_text(json.dumps(content, ensure_ascii=False))
    assert lint(path)[1]["reason"] == "BRIEF_LIMIT"
