"""Local association, retry and retention semantics through command invocation."""

import json
from pathlib import Path
from uuid import uuid4

from devkit.app import create_service
from devkit.runs import RunStore

from tests.beads_helpers import REF, configure


def test_association_is_idempotent_and_protects_evidence(beads_project):
    service = create_service(beads_project)
    target = service.execute("core.doctor")
    original = Path(target["evidence_path"]).read_bytes()
    arguments = {"ref": REF, "run_id": target["run_id"]}
    first = service.execute("beads.evidence.associate", arguments)
    second = service.execute("beads.evidence.associate", arguments)
    assert first["result"] == second["result"]
    assert first["result"]["status"] == "success", first
    assert first["result"]["data"]["references"] == [REF]
    assert Path(target["evidence_path"]).read_bytes() == original
    store = RunStore(service.settings.state_root)
    assert store.show(target["run_id"], beads_project)["references"] == [REF]
    plan = store.prune(beads_project, {"max_age_days": 0, "keep_last": 0}, apply=True)
    assert target["run_id"] not in plan["deleted"]
    assert Path(target["evidence_path"]).exists()
    calls = [
        json.loads(line)["argv"][3]
        for line in (beads_project / "calls.jsonl").read_text().splitlines()
    ]
    assert set(calls) <= {"version", "context", "list"}


def test_reference_failure_and_evidence_failure_retries(beads_project, monkeypatch):
    from devkit import invocation, runs

    service = create_service(beads_project)
    target = service.execute("core.doctor")
    arguments = {"ref": REF, "run_id": target["run_id"]}
    store = RunStore(service.settings.state_root)

    def fail(*args, **kwargs):
        raise OSError("Synthetic failure")

    with monkeypatch.context() as patch:
        patch.setattr(runs, "_save_references", fail)
        result = service.execute("beads.evidence.associate", arguments)
    assert result["result"]["reason"] == "REFERENCE_WRITE_FAILED"
    assert store.show(target["run_id"], beads_project)["references"] == []
    original = invocation.write_bundle

    def fail_association(state, envelope):
        if envelope["command"] == "beads.evidence.associate":
            raise OSError("Synthetic invocation evidence failure")
        return original(state, envelope)

    with monkeypatch.context() as patch:
        patch.setattr(invocation, "write_bundle", fail_association)
        result = service.execute("beads.evidence.associate", arguments)
    assert result["result"]["reason"] == "EVIDENCE_WRITE_FAILED"
    assert result["observed_result"]["status"] == "success"
    assert store.show(target["run_id"], beads_project)["references"] == [REF]
    retry = service.execute("beads.evidence.associate", arguments)
    assert retry["result"]["data"]["references"] == [REF]


def test_association_requires_existing_item_and_same_project_run(beads_project):
    service = create_service(beads_project)
    target = service.execute("core.doctor")
    args = {"ref": REF, "run_id": target["run_id"]}
    configure(beads_project, show=[])
    assert (
        service.execute("beads.evidence.associate", args)["result"]["reason"]
        == "BEADS_ITEM_UNAVAILABLE"
    )
    assert (
        RunStore(service.settings.state_root).show(target["run_id"], beads_project)["references"]
        == []
    )
    configure(beads_project)
    other = beads_project.parent / "other"
    other.mkdir()
    foreign = create_service(other).execute("core.doctor")
    result = service.execute("beads.evidence.associate", {**args, "run_id": foreign["run_id"]})
    assert result["result"]["status"] == "blocked"
    assert RunStore(service.settings.state_root).show(foreign["run_id"], other)["references"] == []
    result = service.execute("beads.evidence.associate", {**args, "run_id": str(uuid4())})
    assert result["result"]["status"] == "blocked"


def test_incomplete_run_is_not_associated(beads_project):
    service = create_service(beads_project)
    run_id = str(uuid4())
    (service.settings.state_root / "runs" / run_id).mkdir(parents=True)
    result = service.execute("beads.evidence.associate", {"ref": REF, "run_id": run_id})
    assert result["result"]["reason"] == "RUN_NOT_FOUND"


def test_failed_verification_can_be_linked_without_becoming_success(beads_project):
    service = create_service(beads_project)
    target = service.execute("unknown.command")
    assert target["result"]["status"] == "error"
    result = service.execute("beads.evidence.associate", {"ref": REF, "run_id": target["run_id"]})
    assert result["result"]["status"] == "success"
    assert result["result"]["data"]["verification_status"] == "error"
    assert json.loads(Path(target["evidence_path"]).read_text())["result"]["status"] == "error"
