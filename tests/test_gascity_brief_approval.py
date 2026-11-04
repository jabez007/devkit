"""Approval command contracts with a disposable native-command adapter."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1] / "integrations/gascity/base"
FAKE_GC = r"""
import json, os, pathlib, sys
path = pathlib.Path(os.environ['FAKE_BEADS'])
state = json.loads(path.read_text())
args = sys.argv[1:]
assert args[:1] == ['--city']
args = args[2:]
assert args.pop(0) == 'bd'
with path.with_suffix('.calls').open('a') as stream:
    stream.write(json.dumps(args) + '\n')
command = args.pop(0)
if command == 'show':
    print(json.dumps([state[args[0]]]))
elif command == 'list':
    field = args[args.index('--metadata-field') + 1]
    key, value = field.split('=', 1)
    print(json.dumps([bead for bead in state.values() if bead['metadata'].get(key) == value]))
elif command == 'update':
    identity = args.pop(0)
    while '--set-metadata' in args:
        offset = args.index('--set-metadata')
        key, value = args[offset + 1].split('=', 1)
        state[identity]['metadata'][key] = value
        del args[offset:offset + 2]
    path.write_text(json.dumps(state))
    print('[]')
elif command == 'close':
    identity = args[0]
    if os.environ.get('FAKE_FAIL_CLOSE') == identity:
        sys.exit(1)
    state[identity]['status'] = 'closed'
    path.write_text(json.dumps(state))
    print('[]')
else:
    sys.exit(1)
"""


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    for key in ("DEVKIT_UNATTENDED", "GIT_DIR", "GIT_WORK_TREE"):
        monkeypatch.delenv(key, raising=False)
    city = tmp_path / "city"
    city.mkdir()
    state = {
        "task-one": dict(id="task-one", status="open", metadata={}),
        "run-one": dict(id="run-one", status="open", metadata={}),
        "approve-one": dict(
            id="approve-one",
            status="open",
            metadata={
                "gc.root_bead_id": "run-one",
                "gc.step_ref": "brief.approve",
                "devkit.brief.role": "approval",
                "devkit.task": "task-one",
            },
        ),
        "gate-one": dict(
            id="gate-one",
            status="open",
            metadata={
                "gc.root_bead_id": "run-one",
                "gc.step_ref": "brief.gate-approve",
                "gc.gate_type": "human",
            },
        ),
    }
    backend = tmp_path / "beads.json"
    backend.write_text(json.dumps(state))
    gc = tmp_path / "gc"
    gc.write_text(f"#!{sys.executable}\n" + FAKE_GC)
    gc.chmod(0o700)
    monkeypatch.setenv("GC_BIN", str(gc))
    monkeypatch.setenv("GC_CITY_PATH", str(city))
    monkeypatch.setenv("GC_PACK_STATE_DIR", str(tmp_path / "pack-state"))
    monkeypatch.setenv("FAKE_BEADS", str(backend))
    brief = tmp_path / "brief.json"
    brief.write_text(
        json.dumps(
            dict(
                schema_version=1,
                task_id="task-one",
                problem="Partial deliveries are unclear.",
                acceptance_criteria=["Four of ten shipped leaves six outstanding."],
                approach="Show delivered and outstanding quantities separately.",
                scope=dict(in_scope=["Partial deliveries"], out_of_scope=["Billing"]),
                open_questions=[],
            )
        )
    )
    return brief, backend


def command(*arguments, environment=None):
    result = subprocess.run(
        [sys.executable, str(BASE / "assets/brief.py"), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip(), result.stderr
    return result.returncode, json.loads(result.stdout)


def record(workflow):
    code, result = command(
        "record", str(workflow[0]), "--task", "task-one", "--workflow", "run-one"
    )
    assert code == 0, result
    return result


def test_record_links_native_task_gate_and_immutable_exact_artifact(workflow):
    result = record(workflow)
    artifact = Path(result["path"])
    assert artifact.read_bytes() == workflow[0].read_bytes()
    assert artifact.stat().st_mode & 0o777 == 0o400
    metadata = json.loads(workflow[1].read_text())["run-one"]["metadata"]
    assert metadata["devkit.brief.task"] == "task-one"
    assert metadata["devkit.brief.sha256"] == result["sha256"]
    assert metadata["devkit.brief.gate"] == "gate-one"
    assert metadata["devkit.brief.approval"] == "approve-one"
    assert record(workflow)["sha256"] == result["sha256"]


def test_approval_requires_human_and_exact_hash(workflow):
    saved = record(workflow)
    code, blocked = command(
        "approve",
        "--workflow",
        "run-one",
        "--sha256",
        saved["sha256"],
        environment={**os.environ, "DEVKIT_UNATTENDED": "1"},
    )
    assert code == 2 and blocked["reason"] == "HUMAN_APPROVAL_REQUIRED"
    assert json.loads(workflow[1].read_text())["gate-one"]["status"] == "open"
    code, wrong = command("approve", "--workflow", "run-one", "--sha256", "0" * 64)
    assert code == 3 and wrong["reason"] == "BRIEF_HASH_MISMATCH"
    assert json.loads(workflow[1].read_text())["gate-one"]["status"] == "open"


def test_verified_approval_survives_new_invocations_and_source_edits(workflow):
    saved = record(workflow)
    assert (
        command("verify", "--workflow", "run-one", "--task", "task-one")[1]["reason"]
        == "BRIEF_PENDING_APPROVAL"
    )
    assert command("approve", "--workflow", "run-one", "--sha256", saved["sha256"])[0] == 0
    workflow[0].write_text("{}")
    code, verified = command("verify", "--workflow", "run-one", "--task", "task-one")
    assert code == 0 and verified["sha256"] == saved["sha256"], verified
    state = json.loads(workflow[1].read_text())
    assert state["gate-one"]["status"] == state["approve-one"]["status"] == "closed"
    assert state["gate-one"]["metadata"]["devkit.brief.approved_sha256"] == saved["sha256"]


def test_recording_another_revision_requires_new_workflow(workflow):
    record(workflow)
    content = json.loads(workflow[0].read_text())
    content["problem"] = "Delivered quantities are unclear after cancellation."
    workflow[0].write_text(json.dumps(content))
    code, result = command(
        "record", str(workflow[0]), "--task", "task-one", "--workflow", "run-one"
    )
    assert code == 3 and result["reason"] == "BRIEF_REVISION_REQUIRES_NEW_WORKFLOW", result


def test_artifact_tampering_never_becomes_approved(workflow):
    saved = record(workflow)
    artifact = Path(saved["path"])
    artifact.chmod(0o600)
    changed = json.loads(artifact.read_text())
    changed["problem"] = "Changed after review."
    artifact.write_text(json.dumps(changed))
    code, result = command("approve", "--workflow", "run-one", "--sha256", saved["sha256"])
    assert code == 3 and result["reason"] == "BRIEF_HASH_MISMATCH"
    assert json.loads(workflow[1].read_text())["gate-one"]["status"] == "open"


def test_closed_gate_without_matching_approval_metadata_is_not_approved(workflow):
    record(workflow)
    state = json.loads(workflow[1].read_text())
    state["gate-one"]["status"] = state["approve-one"]["status"] = "closed"
    workflow[1].write_text(json.dumps(state))
    code, result = command("verify", "--workflow", "run-one", "--task", "task-one")
    assert code == 2 and result["reason"] == "BRIEF_PENDING_APPROVAL"


def test_gate_close_failure_is_recoverable_and_never_passes_verification(workflow, monkeypatch):
    saved = record(workflow)
    monkeypatch.setenv("FAKE_FAIL_CLOSE", "gate-one")
    assert command("approve", "--workflow", "run-one", "--sha256", saved["sha256"])[0] != 0
    assert command("verify", "--workflow", "run-one", "--task", "task-one")[0] == 2
    monkeypatch.delenv("FAKE_FAIL_CLOSE")
    assert command("approve", "--workflow", "run-one", "--sha256", saved["sha256"])[0] == 0
    assert command("verify", "--workflow", "run-one", "--task", "task-one")[0] == 0


def test_human_review_shows_the_exact_bound_brief(workflow):
    saved = record(workflow)
    code, shown = command("show", "--workflow", "run-one")
    assert code == 0
    assert shown["sha256"] == saved["sha256"]
    assert shown["brief"] == json.loads(workflow[0].read_text())


def test_resume_finds_approval_by_task_without_cooking_another_workflow(workflow):
    saved = record(workflow)
    assert command("approve", "--workflow", "run-one", "--sha256", saved["sha256"])[0] == 0
    code, result = command("resume", "--task", "task-one")
    assert code == 0 and result["workflow"] == "run-one", result
    assert result["sha256"] == saved["sha256"]


def test_resume_refuses_ambiguous_recorded_workflows(workflow):
    record(workflow)
    state = json.loads(workflow[1].read_text())
    state["run-two"] = {**state["run-one"], "id": "run-two"}
    workflow[1].write_text(json.dumps(state))
    code, result = command("resume", "--task", "task-one")
    assert code == 3 and result["reason"] == "BRIEF_RESUME_AMBIGUOUS"
