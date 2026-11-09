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


def test_pack_command_runs_in_native_gate_path_without_interactive_shims(brief):
    result = subprocess.run(
        [str(BASE / "commands/brief/run.sh"), "lint", str(brief[0])],
        env={**os.environ, "GC_PACK_DIR": str(BASE), "PATH": "/usr/local/bin:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "success"


@pytest.mark.parametrize(
    "prescription,kind",
    [
        ("Edit addons/sale/models/order.py to store the quantity.", "file_path"),
        ("Change models\\order.py before shipping.", "file_path"),
        ("Read /settings before shipping.", "file_path"),
        ("Read ~/settings before shipping.", "file_path"),
        (r"Read C:\settings before shipping.", "file_path"),
        ("Update the res.partner model.", "dotted_name"),
        ("Update StockPicking.actionConfirm before shipping.", "dotted_name"),
        ("Update res.Partner before shipping.", "dotted_name"),
        ("Change SALES.ORDER before shipping.", "dotted_name"),
        ("Call button_validate() once.", "call"),
        ("Call confirm () once.", "call"),
        ("Call confirm\t( ) once.", "call"),
        ("Add delivered_qty to the form.", "identifier"),
        ("Change _compute_qty to calculate the remainder.", "identifier"),
        ("Change _validate to check the quantity.", "identifier"),
        ("Change __init__ to set the quantity.", "identifier"),
        ("Run the command with --test-enable.", "command_flag"),
        ("Use `python` to calculate the remainder.", "code"),
        ("Update package.json.", "source_file"),
        ("Update README.md before shipping.", "source_file"),
        ("Update README.MD before shipping.", "source_file"),
        ("Update DELIVERY.PY before shipping.", "source_file"),
        ("Update settings.ini before shipping.", "source_file"),
        ("Update settings.cfg before shipping.", "source_file"),
        ("Update requirements.txt before shipping.", "source_file"),
        ("Update dependencies.lock before shipping.", "source_file"),
        ("Update .env before shipping.", "source_file"),
        ("Update .env.production before shipping.", "source_file"),
        ("Update .gitignore before shipping.", "source_file"),
        ("Update .dockerignore before shipping.", "source_file"),
        ("Update Dockerfile before shipping.", "source_file"),
        ("Update Makefile before shipping.", "source_file"),
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
    "behavior",
    [
        "Show the outstanding quantity (including returned items).",
        "Show the delivery state (pending or sent) beside each order.",
        "Ask GitHub reviewers to confirm the delivery behavior.",
        "Accept quantities such as 1.25 and 10.5 without rounding them to whole items.",
    ],
)
def test_lint_accepts_prose_parentheses_product_names_and_decimals(brief, behavior):
    path, content = brief
    content["approach"] = behavior
    path.write_text(json.dumps(content))
    code, result = lint(path)
    assert code == 0 and result["findings"] == [], result


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


def test_lint_bounds_work_for_long_punctuation_separated_words(brief):
    path, content = brief
    content["problem"] = "a-" * 40_000
    path.write_text(json.dumps(content))
    code, result = lint(path)
    assert code == 0 and result["status"] == "success"


@pytest.mark.parametrize("prefix", ["/", "~/", "C:\\"])
def test_lint_bounds_work_for_long_rooted_paths(brief, prefix):
    path, content = brief
    content["problem"] = prefix + "a-" * 40_000
    path.write_text(json.dumps(content))
    code, result = lint(path)
    assert code == 1 and result["reason"] == "PRESCRIPTIVE_BRIEF", result
    assert {finding["kind"] for finding in result["findings"]} == {"file_path"}


def test_lint_caps_findings_and_preserves_their_line_numbers(brief):
    path, content = brief
    content["problem"] = "\n".join(["Change _quantity before shipping."] * 110)
    path.write_text(json.dumps(content))
    code, result = lint(path)
    assert code == 1
    assert result["findings"] == [
        {"section": "problem", "line": line, "kind": "identifier"} for line in range(1, 101)
    ]
