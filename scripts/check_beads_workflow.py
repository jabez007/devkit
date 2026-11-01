"""Synthetic development workflow and native worktree compatibility probes.

Run with the same root/wheels/constraints arguments as check_beads_wheels.py.
Worktrees share one native ledger but retain separate Devkit grants and evidence.
"""

import json
import os
import shutil
import sys
from pathlib import Path

from check_beads_lifecycle import EFFECTS, grant, invoke
from check_beads_wheels import READ, association_parity, bd, setup
from check_wheels import cli, run


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


def create_worktrees(root, project, env, binary):
    native_env = dict(env)
    native_env.pop("BEADS_DIR")
    checkouts = []
    for mode in ("git", "beads"):
        checkout = root / f"{mode}-worktree"
        if mode == "git":
            run("git", "worktree", "add", "-b", mode, str(checkout), cwd=project, env=native_env)
            shutil.rmtree(
                checkout / ".beads"
            )  # Disposable tracked metadata, never the shared ledger.
        else:
            bd(binary, project, native_env, "worktree", "create", str(checkout), "--branch", mode)
        (checkout / "branch.txt").write_text(mode)
        commit(checkout, env, f"Distinct {mode} checkout revision")
        checkouts.append(checkout)
    return checkouts


def authorize_worktrees(root, checkouts):
    commands = {
        f"beads.{name}": READ
        for name in (
            "workspace",
            "item.show",
            "ready",
            "dependencies",
            "evidence.associate",
        )
    }
    commands.update(
        {
            f"beads.item.{name}": EFFECTS
            for name in (
                "create",
                "claim",
                "update",
                "comment",
                "close",
            )
        }
    )
    commands["go.test"] = EFFECTS
    with (root / "config/devkit/policy.toml").open("a") as stream:
        stream.write(f"\n[profiles.linked]\nprojects={json.dumps([str(p) for p in checkouts])}\n")
        for command, effects in commands.items():
            stream.write(f'[profiles.linked.commands."{command}"]\n')
            stream.write(f'effects={json.dumps(effects)}\nsurfaces=["cli","python","mcp"]\n')


def verify_checkout(root, project, env, reference):
    check = cli(root, project, env, "check", "verify")
    revision = run(
        "git", "rev-parse", "HEAD", cwd=project, capture_output=True, text=True
    ).stdout.strip()
    assert check["source"]["revision"] == revision
    assert check["project_root"] == str(project)
    associate_and_review(root, project, env, reference, check)
    rows = cli(root, project, env, "runs", "list", "--reference", reference)["result"]["data"]
    assert [row["run_id"] for row in rows["runs"]] == [check["run_id"]]
    return check


def worktrees(root, project, env, binary):
    checkouts = create_worktrees(root, project, env, binary)
    # Ambient workspace selection cannot redirect Devkit to a different ledger.
    env = {**env, "BEADS_DIR": str(root / "not-a-workspace")}
    item = invoke(root, project, env, "create", {"title": "Sequential linked checkout task"})
    reference = item["result"]["data"]["item"]["ref"]
    main_run = verify_checkout(root, project, env, reference)
    for checkout in checkouts:
        denied = invoke(root, checkout, env, "create", {"title": "Must not be created"}, expected=2)
        assert denied["result"]["reason"] == "DENIED"
        arguments = {"ref": reference, "run_id": main_run["run_id"]}
        denied_link = cli(
            root,
            checkout,
            env,
            "run",
            "beads.evidence.associate",
            "--args",
            json.dumps(arguments),
            expected=2,
        )
        association_parity(root, checkout, env, arguments, denied_link["result"])
    authorize_worktrees(root, checkouts)
    runs = [main_run]
    for checkout in checkouts:
        workspace = cli(root, checkout, env, "run", "beads.workspace")["result"]["data"][
            "workspace"
        ]
        assert workspace["project_id"] == reference.split(":")[1]
        assert workspace["workspace_root"] == str(project)
        assert workspace["checkout_root"] == str(checkout) and workspace["is_worktree"] is True
        assert workspace["concurrency"] == "sequential-only"
        if checkout == checkouts[0]:
            claimed = invoke(root, checkout, env, "claim", {"ref": reference})
            assert claimed["result"]["data"]["item"]["status"] == "in_progress"
        else:
            invoke(
                root,
                checkout,
                env,
                "update",
                {
                    "ref": reference,
                    "title": "Reviewed from second checkout",
                    "if_status": "in_progress",
                },
            )
        check = verify_checkout(root, checkout, env, reference)
        arguments = {"ref": reference, "run_id": check["run_id"]}
        associated = cli(
            root, checkout, env, "run", "beads.evidence.associate", "--args", json.dumps(arguments)
        )
        association_parity(root, checkout, env, arguments, associated["result"])
        foreign = cli(
            root,
            checkout,
            env,
            "run",
            "beads.evidence.associate",
            "--args",
            json.dumps({"ref": reference, "run_id": main_run["run_id"]}),
            expected=2,
        )
        assert foreign["result"]["reason"] == "RUN_NOT_FOUND"
        runs.append(check)
    closed = invoke(
        root,
        checkouts[1],
        env,
        "close",
        {"ref": reference, "reason": "Sequential checkout verification reviewed"},
    )
    assert closed["result"]["data"]["item"]["status"] == "closed"
    shown = cli(
        root, project, env, "run", "beads.item.show", "--args", json.dumps({"ref": reference})
    )
    assert shown["result"]["data"]["item"]["status"] == "closed"
    assert len({check["source"]["revision"] for check in runs}) == 3
    for checkout in [project, *checkouts]:
        cli(
            root,
            checkout,
            env,
            "runs",
            "prune",
            "--older-than-days",
            "0",
            "--keep-last",
            "0",
            "--apply",
        )
    assert all(Path(check["evidence_path"]).exists() for check in runs)
    rows = cli(root, project, env, "runs", "list", "--reference", reference, "--all-projects")[
        "result"
    ]["data"]["runs"]
    assert {row["run_id"] for row in rows} == {check["run_id"] for check in runs}
    return {"reference": reference, "runs": [check["run_id"] for check in runs]}


def main():
    root, wheels, constraints = map(Path, sys.argv[1:4])
    root.mkdir()
    binary = Path(os.environ["DEVKIT_BEADS_BINARY"]).resolve()
    project, env, _, _ = setup(root, wheels, constraints, "go", binary)
    report = development(root, project, env)
    report["worktrees"] = worktrees(root, project, env, binary)
    (root / "assessment.json").write_text(json.dumps(report, indent=2))
    print(
        "PASS: sequential main + two linked worktrees, scoped grants/evidence, "
        "three surfaces and retention"
    )


if __name__ == "__main__":
    main()
