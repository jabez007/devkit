"""Real Git topology, controlled Beads identity, and public invocation semantics."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from threading import Event, Timer

import pytest
from devkit.app import create_service

from tests.beads_helpers import REF, SCOPE, configure


def git(project, *arguments):
    return subprocess.run(
        ["git", "-C", str(project), *arguments], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def linked(beads_project):
    git(beads_project, "add", ".")
    git(
        beads_project,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "Fixture",
    )
    path = beads_project.parent / "linked checkout"
    git(beads_project, "worktree", "add", "-b", "linked", str(path))
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(policy.read_text().replace(str(beads_project), str(path)))
    configure(
        path,
        context={
            "beads_dir": str(beads_project / ".beads"),
            "repo_root": str(beads_project),
            "cwd_repo_root": str(path),
            "is_worktree": True,
        },
    )
    return beads_project, path


def test_linked_checkout_without_local_metadata_uses_shared_identity(linked):
    main, path = linked
    assert not (path / ".beads").exists()
    result = create_service(path).execute("beads.item.show", {"ref": REF})
    assert result["result"]["status"] == "success", result
    workspace = result["result"]["data"]["workspace"]
    assert workspace["project_id"] == SCOPE
    assert workspace["checkout_root"] == str(path)
    assert workspace["workspace_root"] == str(main)
    assert workspace["is_worktree"] is True
    assert workspace["concurrency"] == "sequential-only"
    assert result["project_root"] == str(path)
    calls = [json.loads(line) for line in (path / "calls.jsonl").read_text().splitlines()]
    listing = [call for call in calls if call["argv"][3] == "list"]
    assert listing[0]["env"]["BEADS_DIR"] == str(main / ".beads")


@pytest.mark.parametrize(
    "damage",
    [
        "copied_gitfile",
        "other_registered_gitfile",
        "wrong_backlink",
        "beads_symlink",
        "git_symlink",
        "redirect",
        "missing_main_ledger",
    ],
)
def test_unsafe_topology_never_starts_beads(linked, damage):
    main, path = linked
    if damage == "copied_gitfile":
        other = path.parent / "unregistered"
        shutil.copytree(path, other)
        policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
        policy.write_text(policy.read_text().replace(str(path), str(other)))
        path = other
    elif damage == "other_registered_gitfile":
        other = path.parent / "registered sibling"
        git(main, "worktree", "add", "-b", "sibling", str(other))
        (path / ".git").write_bytes((other / ".git").read_bytes())
    elif damage == "wrong_backlink":
        directory = Path(git(path, "rev-parse", "--absolute-git-dir"))
        (directory / "gitdir").write_text(str(main / ".git"))
    elif damage == "beads_symlink":
        (path / ".beads").symlink_to(main / ".beads", target_is_directory=True)
    elif damage == "git_symlink":
        (path / ".git").rename(path / "git-link")
        (path / ".git").symlink_to(path / "git-link")
    elif damage == "missing_main_ledger":
        (main / ".beads").rmdir()
    else:
        (path / ".beads").mkdir()
        (path / ".beads/redirect").write_text(str(main / ".beads"))
    result = create_service(path).execute("beads.item.create", {"actor": "fixture", "title": "No"})
    assert result["result"]["status"] == "blocked", result
    assert not (path / "calls.jsonl").exists()
    assert not (path / "write-started").exists()


def test_native_move_requires_a_new_checkout_grant(linked):
    main, path = linked
    moved = path.parent / "moved checkout"
    git(main, "worktree", "move", str(path), str(moved))
    assert create_service(moved).execute("beads.workspace")["result"]["reason"] == "DENIED"
    assert not (moved / "calls.jsonl").exists()
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(policy.read_text().replace(str(path), str(moved)))
    configure(
        moved,
        context={
            "beads_dir": str(main / ".beads"),
            "repo_root": str(main),
            "cwd_repo_root": str(moved),
            "is_worktree": True,
        },
    )
    assert create_service(moved).execute("beads.workspace")["result"]["status"] == "success"


def test_main_grant_does_not_authorize_linked_checkout(linked):
    main, path = linked
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(policy.read_text().replace(str(path), str(main)))
    result = create_service(path).execute("beads.workspace")
    assert result["result"]["reason"] == "DENIED"
    assert not (path / "calls.jsonl").exists()


def test_uuid_change_before_write_blocks_without_uncertainty(beads_project):
    configure(
        beads_project,
        change_context_after=3,
        changed_context={
            "project_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    result = create_service(beads_project).execute(
        "beads.item.create", {"actor": "fixture", "title": "No"}
    )
    assert result["result"]["reason"] == "WORKSPACE_MISMATCH", result
    assert not result["result"]["data"].get("mutation_may_have_occurred")
    assert not (beads_project / "write-started").exists()


@pytest.mark.parametrize("field", ["cwd_repo_root", "repo_root", "beads_dir"])
def test_native_paths_must_match_git_topology(linked, field):
    main, path = linked
    context = {
        "beads_dir": str(main / ".beads"),
        "repo_root": str(main),
        "cwd_repo_root": str(path),
        "is_worktree": True,
    }
    context[field] = str(path.parent / "unrelated")
    configure(path, context=context)
    result = create_service(path).execute("beads.workspace")
    assert result["result"]["reason"] == "WORKSPACE_MISMATCH"


def test_binding_cannot_change_uuid(linked):
    main, path = linked
    configure(
        path,
        context={
            "beads_dir": str(main / ".beads"),
            "repo_root": str(main),
            "cwd_repo_root": str(path),
            "is_worktree": True,
        },
        change_context_after=2,
        changed_context={
            "project_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    result = create_service(path).execute("beads.workspace")
    assert result["result"]["reason"] == "WORKSPACE_MISMATCH"


def test_older_adapter_trust_does_not_enable_worktrees(linked):
    _, path = linked
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(policy.read_text().replace('"0.3.0"', '"0.2.0"'))
    result = create_service(path, diagnostic=True).execute("core.doctor")
    assert result["result"]["status"] == "blocked"
    assert not (path / "calls.jsonl").exists()


def test_git_inspection_is_cancellable(linked):
    _, path = linked
    wrapper = Path(os.environ["PATH"].split(os.pathsep)[0]) / "git"
    wrapper.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    wrapper.chmod(0o755)
    cancellation = Event()
    timer = Timer(0.2, cancellation.set)
    timer.start()
    try:
        result = create_service(path).execute("beads.workspace", cancellation=cancellation)
    finally:
        timer.join()
    assert result["result"]["status"] == "cancelled"
    assert not (path / "calls.jsonl").exists()
