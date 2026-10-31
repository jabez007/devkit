"""Synthetic development workflow and native worktree compatibility probes.

Run with the same root/wheels/constraints arguments as check_beads_wheels.py.
Worktree probes assert Devkit's current refusal, not adapter worktree support.
"""

import json
import os
import sys
from pathlib import Path

from check_beads_lifecycle import grant, invoke
from check_beads_wheels import READ, bd, setup
from check_wheels import cli, policy, run


def commit(project, env, message):
    run("git", "add", ".", cwd=project, env=env)
    run(
        "git",
        "-c",
        "user.name=Devkit Acceptance",
        "-c",
        "user.email=acceptance@example.invalid",
        "commit",
        "-qm",
        message,
        cwd=project,
        env=env,
    )


def associate_and_review(root, project, env, reference, check):
    arguments = json.dumps({"ref": reference, "run_id": check["run_id"]})
    for _ in range(2):
        linked = cli(root, project, env, "run", "beads.evidence.associate", "--args", arguments)
        assert linked["result"]["data"]["references"] == [reference]
    shown = cli(root, project, env, "runs", "show", check["run_id"])["result"]["data"]
    assert shown["run"]["result"] == check["result"]
    assert shown["references"] == [reference]


def development(root, project, env):
    grant(root, project)
    (project / ".gitignore").write_text(".beads/\n")
    source = project / "quantity.go"
    source.write_text(
        "package demo\nfunc Remaining(stock, requested int) int { return stock + requested }\n"
    )
    (project / "quantity_test.go").write_text(
        'package demo\nimport "testing"\nfunc TestRemaining(t *testing.T) { '
        'if got := Remaining(10, 3); got != 7 { t.Fatalf("remaining = %d; want 7", got) } }\n'
    )
    commit(project, env, "Synthetic quantity fixture with regression test")
    created = invoke(
        root,
        project,
        env,
        "create",
        {"title": "Correct remaining inventory calculation", "description": "Subtract requests"},
    )
    reference = created["result"]["data"]["item"]["ref"]
    claimed = invoke(root, project, env, "claim", {"ref": reference})
    assert claimed["result"]["data"]["item"]["status"] == "in_progress"
    failed = cli(root, project, env, "check", "verify", expected=1)
    source.write_text(source.read_text().replace("stock + requested", "stock - requested"))
    passed = cli(root, project, env, "check", "verify")
    for check in (failed, passed):
        associate_and_review(root, project, env, reference, check)
    diff = run("git", "diff", "--", "quantity.go", cwd=project, capture_output=True, text=True)
    assert "return stock - requested" in diff.stdout
    review = (
        "Synthetic review: inspected subtraction diff and test 10-3=7; "
        f"failing run {failed['run_id']}; passing run {passed['run_id']}. "
        "No deployment tested; this is not independent human approval."
    )
    invoke(root, project, env, "comment", {"ref": reference, "text": review})
    shown = cli(
        root, project, env, "run", "beads.item.show", "--args", json.dumps({"ref": reference})
    )
    assert shown["result"]["data"]["item"]["status"] == "in_progress"
    closed = invoke(root, project, env, "close", {"ref": reference, "reason": "Review completed"})
    assert closed["result"]["data"]["item"]["status"] == "closed"
    cli(
        root, project, env, "runs", "prune", "--older-than-days", "0", "--keep-last", "0", "--apply"
    )
    assert all(Path(check["evidence_path"]).exists() for check in (failed, passed))
    commit(project, env, "Correct remaining inventory calculation")
    return {"reference": reference, "failed_run": failed["run_id"], "passed_run": passed["run_id"]}


def worktrees(root, project, env, binary, reference):
    native_env = dict(env)
    native_env.pop("BEADS_DIR")
    context = bd(binary, project, native_env, "--readonly", "--sandbox", "--json", "context")
    observations = {}
    for mode in ("git", "beads"):
        worktree = root / f"{mode}-worktree"
        if mode == "git":
            run("git", "worktree", "add", "-b", mode, str(worktree), cwd=project, env=native_env)
        else:
            bd(binary, project, native_env, "worktree", "create", str(worktree), "--branch", mode)
        resolved = bd(binary, worktree, native_env, "--readonly", "--sandbox", "--json", "context")
        assert resolved["project_id"] == context["project_id"]
        assert resolved["beads_dir"] == str(project / ".beads")
        assert resolved["is_worktree"] is True and resolved["is_redirected"] is False
        rows = bd(
            binary,
            worktree,
            native_env,
            "--readonly",
            "--sandbox",
            "--json",
            "list",
            "--id",
            reference.split(":")[-1],
            "--all",
        )
        assert rows[0]["status"] == "closed"
        created = bd(
            binary,
            worktree,
            native_env,
            "--sandbox",
            "--json",
            "--actor=devkit-acceptance",
            "create",
            f"Synthetic {mode} worktree task",
            "--type",
            "task",
        )
        shared = bd(
            binary,
            project,
            native_env,
            "--readonly",
            "--sandbox",
            "--json",
            "list",
            "--id",
            created["id"],
            "--all",
        )
        assert shared[0]["id"] == created["id"]
        policy(root, worktree, ["beads", "go"], {"beads.workspace": READ})
        blocked = cli(root, worktree, env, "run", "beads.workspace", expected=2)
        assert blocked["result"]["reason"] == "UNSUPPORTED_BEADS_WORKSPACE"
        observations[mode] = {"native_context": resolved, "devkit": blocked["result"]}
    return observations


def main():
    root, wheels, constraints = map(Path, sys.argv[1:4])
    root.mkdir()
    binary = Path(os.environ["DEVKIT_BEADS_BINARY"]).resolve()
    project, env, _, _ = setup(root, wheels, constraints, "go", binary)
    report = development(root, project, env)
    report["worktrees"] = worktrees(root, project, env, binary, report["reference"])
    (root / "assessment.json").write_text(json.dumps(report, indent=2))
    print(
        "PASS: Go repair/review workflow, retained evidence, native worktrees and adapter refusal"
    )


if __name__ == "__main__":
    main()
