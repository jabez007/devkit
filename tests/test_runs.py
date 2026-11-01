import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from mccann_hub.devkit.app import create_service


@pytest.fixture
def runs(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    executable = str(Path(".venv/bin/devkit").resolve())

    def cli(*args, expected=0, selected=project):
        proc = subprocess.run(
            [executable, "--project", str(selected), "--json", "runs", *args],
            capture_output=True,
            text=True,
            env=dict(os.environ),
        )
        assert proc.returncode == expected, proc.stdout + proc.stderr
        return json.loads(proc.stdout)["result"]["data"]

    def create(age=40, selected=project, **updates):
        result = create_service(selected).execute("core.doctor")
        path = Path(result["evidence_path"])
        saved = json.loads(path.read_text())
        saved["finished_at"] = (datetime.now(UTC) - timedelta(days=age)).isoformat()
        saved.update(updates)
        path.write_text(json.dumps(saved))
        return result["run_id"], path

    return cli, create, project, tmp_path / "state/devkit/runs"


def test_list_and_show_do_not_create_evidence_or_load_plugins(runs):
    cli, create, project, root = runs
    run_id, _ = create()
    (project / "devkit.toml").write_text('plugins=["not-installed"]')
    assert cli("list")["runs"][0]["run_id"] == run_id
    assert cli("show", run_id)["run"]["run_id"] == run_id
    assert len(list(root.iterdir())) == 1


def test_pruning_defaults_to_preview_and_rechecks_new_references(runs):
    cli, create, _, _ = runs
    first, first_path = create()
    second, second_path = create()
    plan = cli("prune", "--keep-last", "0")
    assert set(plan["candidates"]) == {first, second}
    assert first_path.exists() and second_path.exists()
    cli("pin", first, "--reference", "work:active-123")
    applied = cli("prune", "--keep-last", "0", "--apply")
    assert applied["deleted"] == [second]
    assert first_path.exists() and not second_path.exists()
    assert cli("show", first)["references"] == ["work:active-123"]
    cli("unpin", first, "--reference", "work:active-123")
    assert cli("prune", "--keep-last", "0", "--apply")["deleted"] == [first]


def test_retention_age_count_and_project_scope(runs):
    cli, create, project, _ = runs
    old, old_path = create(age=50)
    _, kept_path = create(age=40)
    _, fresh_path = create(age=1)
    other = project.parent / "other"
    other.mkdir()
    _, other_path = create(selected=other)
    assert cli("list")["total"] == 3
    assert cli("list", "--all-projects")["total"] == 4
    assert cli("prune", "--keep-last", "2", "--apply")["deleted"] == [old]
    assert not old_path.exists()
    assert all(p.exists() for p in (kept_path, fresh_path, other_path))


def test_pins_and_active_parent_protect_related_runs(runs):
    cli, create, _, _ = runs
    parent, parent_path = create()
    child, child_path = create(parent_run_id=parent)
    _, active_path = create(parent_run_id=str(uuid4()))
    _, work_path = create(work_item_ref="beads:project:active")
    cli("pin", child, "--reference", "pr:123")
    result = cli("prune", "--keep-last", "0", "--apply")
    assert not result["deleted"]
    assert all(p.exists() for p in (parent_path, child_path, active_path, work_path))
    cli("unpin", child, "--reference", "pr:123")
    assert set(cli("prune", "--keep-last", "0", "--apply")["deleted"]) == {parent, child}


def test_retention_is_operator_configured(runs):
    cli, create, project, _ = runs
    run_id, path = create(age=10)
    config = project.parent / "config/devkit"
    config.mkdir(parents=True)
    (config / "retention.toml").write_text("max_age_days=5\nkeep_last=0\n")
    (config / "retention.toml").chmod(0o600)
    assert cli("prune")["candidates"] == [run_id]
    assert path.exists()


@pytest.mark.parametrize(
    "corruption",
    [
        "symlink",
        "invalid_json",
        "invalid_references",
        "invalid_parent",
        "invalid_work_ref",
    ],
)
def test_unsafe_evidence_blocks_pruning_without_deleting_anything(runs, corruption):
    cli, create, _, _ = runs
    _, good = create()
    _, bad = create()
    if corruption == "symlink":
        bad.unlink()
        bad.symlink_to(good)
    elif corruption == "invalid_json":
        bad.write_text("{")
    elif corruption == "invalid_references":
        (bad.parent / "references.json").write_text("not json")
    else:
        evidence = json.loads(bad.read_text())
        evidence["parent_run_id" if corruption == "invalid_parent" else "work_item_ref"] = ""
        bad.write_text(json.dumps(evidence))
    cli("prune", "--keep-last", "0", "--apply", expected=3)
    assert good.exists() and bad.parent.exists()


def test_unknown_artifacts_and_incomplete_runs_are_preserved(runs):
    cli, create, _, root = runs
    _, path = create()
    (path.parent / "unmanaged.txt").write_text("retain")
    incomplete = root / str(uuid4())
    incomplete.mkdir()
    cli("prune", "--keep-last", "0", "--apply")
    assert path.exists() and incomplete.exists()


def test_run_identifiers_cannot_escape_state(runs):
    cli, _, _, _ = runs
    cli("show", "../../outside", expected=3)
    cli("pin", "../../outside", "--reference", "work", expected=3)


def test_reference_updates_are_idempotent_and_independent(runs):
    cli, create, _, _ = runs
    run_id, path = create()
    cli("pin", run_id, "--reference", "work:one")
    cli("pin", run_id, "--reference", "work:one")
    cli("pin", run_id, "--reference", "work:two")
    cli("unpin", run_id, "--reference", "work:one")
    assert cli("show", run_id)["references"] == ["work:two"]
    assert (path.parent / "references.json").stat().st_mode & 0o777 == 0o600
    assert not cli("prune", "--keep-last", "0", "--apply")["deleted"]


def test_reference_listing_is_exact_scoped_and_paginated(runs):
    cli, create, project, root = runs
    reference = "review: arbitrary / café #42"
    other = project.parent / "other"
    other.mkdir()
    first, first_path = create(age=50)
    second, _ = create(age=40)
    foreign, _ = create(selected=other)
    unrelated, _ = create(age=1)
    legacy, _ = create(age=60, work_item_ref=reference)
    for identifier in (first, second, foreign):
        for _ in range(2):
            cli("pin", identifier, "--reference", reference, "--all-projects")
    before = {path: path.read_bytes() for path in root.glob("*/*.json")}
    (project / "devkit.toml").write_text('plugins=["beads-not-installed"]')
    page = cli("list", "--reference", reference, "--limit", "1", "--offset", "1")
    assert page["total"] == 3 and page["offset"] == 1
    assert [row["run_id"] for row in page["runs"]] == [first]
    assert cli("list", "--reference", reference, "--offset", "3")["runs"] == []
    all_projects = cli("list", "--reference", reference, "--all-projects")
    assert {row["run_id"] for row in all_projects["runs"]} == {first, second, foreign, legacy}
    assert cli("list", "--reference", "review:")["total"] == 0
    assert cli("list", "--reference", reference.upper())["total"] == 0
    assert before == {path: path.read_bytes() for path in root.glob("*/*.json")}
    assert cli("prune", "--keep-last", "0", "--older-than-days", "0", "--apply")["deleted"] == [
        unrelated
    ]
    assert first_path.exists()


@pytest.mark.parametrize("foreign", [False, True])
def test_reference_filter_does_not_hide_corrupt_metadata(runs, foreign):
    cli, create, project, root = runs
    selected = project.parent / "other" if foreign else project
    selected.mkdir(exist_ok=True)
    identifier, path = create(selected=selected)
    (path.parent / "references.json").write_text('{"references":["duplicate","duplicate"]}')
    cli("list", "--reference", "unrelated", expected=3)
    assert (root / identifier / "result.json").exists()


def test_concurrent_pruners_remove_each_run_once(runs):
    _, create, project, _ = runs
    ids = {create()[0] for _ in range(5)}
    executable = str(Path(".venv/bin/devkit").resolve())
    command = [
        executable,
        "--project",
        str(project),
        "--json",
        "runs",
        "prune",
        "--keep-last",
        "0",
        "--apply",
    ]
    processes = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    deleted = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stdout + stderr
        deleted.extend(json.loads(stdout)["result"]["data"]["deleted"])
    assert set(deleted) == ids
    assert len(deleted) == len(ids)


def test_prune_failure_is_reported_with_observed_deletions(runs):
    if os.geteuid() == 0:
        pytest.skip("Permission fixture requires a non-root user")
    cli, create, _, _ = runs
    run_id, path = create()
    path.parent.chmod(0o500)
    try:
        result = cli("prune", "--keep-last", "0", "--apply", expected=3)
        assert not result["deleted"]
        assert result["errors"] == [{"run_id": run_id, "reason": "PRUNE_FAILED"}]
        assert path.exists()
    finally:
        path.parent.chmod(0o700)


def test_all_projects_keeps_newest_runs_per_project(runs):
    cli, create, project, _ = runs
    other = project.parent / "second"
    other.mkdir()
    old, _ = create(age=50)
    kept, _ = create(age=40)
    other_old, _ = create(age=60, selected=other)
    other_kept, _ = create(age=45, selected=other)
    result = cli("prune", "--all-projects", "--keep-last", "1")
    assert set(result["candidates"]) == {old, other_old}
    assert {item["run_id"] for item in result["protected"]} == {kept, other_kept}


@pytest.mark.parametrize("settings", ["keep_last=-1", "max_age_days=nan", 'keep_last="zero"'])
def test_invalid_retention_never_deletes_evidence(runs, settings):
    cli, create, project, _ = runs
    _, path = create()
    config = project.parent / "config/devkit"
    config.mkdir(parents=True)
    (config / "retention.toml").write_text(settings)
    (config / "retention.toml").chmod(0o600)
    cli("prune", "--apply", expected=3)
    assert path.exists()


def test_profile_evidence_is_inspectable_and_pruned_as_a_family(runs):
    cli, _, project, _ = runs
    from dataclasses import replace

    from mccann_hub.devkit.contracts import CheckSpec, CommandResult, CommandSpec
    from mccann_hub.devkit.invocation import CommandService
    from mccann_hub.devkit.policy import Policy

    settings = replace(create_service(project).settings, profiles={"quick": ["test.check"]})
    command = CommandSpec("test.run", "Test", lambda ctx, args: CommandResult("success", "OK"))
    grant = {"project": str(project), "effects": [], "surfaces": ["python"]}
    service = CommandService(
        settings,
        (command,),
        Policy(commands={command.id: grant}),
        checks=(CheckSpec("test.check", command.id),),
    )
    result = service.execute("core.check", {"profile": "quick"})
    parent = result["run_id"]
    child = result["result"]["data"]["checks"][0]["run_id"]
    assert cli("show", child)["run"]["parent_run_id"] == parent
    assert set(cli("prune", "--older-than-days", "0", "--keep-last", "0")["candidates"]) == {
        parent,
        child,
    }
