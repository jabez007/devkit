"""Requests cross the real standalone PreToolUse hook interface."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "integrations/unattended"


@pytest.fixture
def guard_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "feature"], cwd=project, check=True)
    subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk"],
        cwd=project,
        check=True,
    )
    return project


def invoke(
    project, tool="Bash", tool_input=None, *, rules=None, unattended="1", raw=None, bead=None
):
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "DEVKIT_", "GC_"))
    }
    if unattended is not None:
        environment["DEVKIT_UNATTENDED"] = unattended
    if bead is not None:
        environment["GC_BEAD_ID"] = bead
    environment["CLAUDE_CONFIG_DIR"] = str(project.parent / "claude")
    arguments = [sys.executable, str(ASSETS / "guard.py")]
    if rules:
        arguments += ["--rules", str(rules)]
    event = {"tool_name": tool, "tool_input": tool_input or {}, "cwd": str(project)}
    result = subprocess.run(
        arguments,
        input=raw if raw is not None else json.dumps(event),
        text=True,
        capture_output=True,
        env=environment,
        cwd=project,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    if not result.stdout:
        return None
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    return decision["permissionDecisionReason"]


@pytest.mark.parametrize(
    "command",
    [
        "git push --force",
        "git push -f origin feature",
        "git push -uf origin feature",
        "git push --force-with-lease origin feature",
        "git push --force-if-includes origin feature",
        "git push origin +main",
        "git push origin +feature:feature",
        "git push --mirror origin",
        "command git push -f origin feature",
        "env MODE=test git push -f origin feature",
        "/usr/bin/env MODE=test /usr/bin/git push -f origin feature",
        "/usr/bin/git push -f origin feature",
        "true && git push -f origin feature",
        "echo $(git push -f origin feature)",
        "bash -c 'git push -f origin feature'",
        "sh -lc 'git push -f origin feature'",
        "git send-pack --force origin feature",
        "timeout 5 git push -f origin feature",
        "nice -n 5 git push -f origin feature",
        "stdbuf -oL git push --force origin feature",
        "git-send-pack --force origin feature",
    ],
)
def test_force_push_forms_are_denied(guard_project, command):
    assert "no-force-push" in invoke(guard_project, tool_input={"command": command})


@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 1",
        "gh pr ready 1",
        "gh pr review 1 --approve",
        "gh pr review 1 -a",
        "gh pr review 1 --approve=true",
        "gh pr create --title Example",
        "gh pr create --draft --draft=false --title Example",
        "gh pr create --body '--draft' --title Example",
    ],
)
def test_pr_publication_is_denied(guard_project, command):
    assert "no-pr-publish" in invoke(guard_project, tool_input={"command": command})


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push origin feature:refs/heads/main",
        "git push origin HEAD:trunk",
        "git push --all origin",
        "git push origin",
        "git push origin '$branch'",
    ],
)
def test_default_protected_and_unknown_destinations_are_denied(guard_project, command):
    assert "no-protected-push" in invoke(guard_project, tool_input={"command": command})


@pytest.mark.parametrize(
    "command",
    [
        "git push --delete origin feature",
        "git push -d origin feature",
        "git push origin :feature",
        "git push --prune origin feature",
    ],
)
def test_remote_deletion_is_denied(guard_project, command):
    assert "no-remote-delete" in invoke(guard_project, tool_input={"command": command})


@pytest.mark.parametrize("command", ["sleep 1 &", "sleep 1 & wait", "nohup sleep 1", "disown"])
def test_background_processes_are_denied(guard_project, command):
    assert "no-background" in invoke(guard_project, tool_input={"command": command})


def test_background_tool_input_is_denied(guard_project):
    assert "no-background" in invoke(
        guard_project, tool_input={"command": "pytest", "run_in_background": True}
    )


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("mcp__github__merge_pull_request", {}),
        ("mcp__github__mark_pull_request_ready_for_review", {}),
        ("mcp__github__pull_request_review_write", {"event": "APPROVE"}),
    ],
)
def test_known_github_mcp_publication_is_denied(guard_project, tool, arguments):
    assert "no-pr-publish" in invoke(guard_project, tool, arguments)


@pytest.mark.parametrize(
    "command",
    [
        "git push origin feature-branch",
        "git push -u origin HEAD:feature-branch",
        "git status --short",
        "gh pr view 1",
        "gh pr create --draft --title 'Example'",
        "pytest -q",
        "timeout 5 pytest -q",
        "nice -n5 pytest -q",
        "stdbuf -oL pytest -q",
        "printf '%s' '&'",
        "printf '%s' 'git push --force'",
        "git --version",
    ],
)
def test_ordinary_foreground_commands_defer_to_existing_permissions(guard_project, command):
    assert invoke(guard_project, tool_input={"command": command}) is None


@pytest.mark.parametrize("value", ["1", "", "0"])
def test_any_set_unattended_value_activates_guard(guard_project, value):
    assert "no-force-push" in invoke(
        guard_project, tool_input={"command": "git push -f"}, unattended=value
    )


def test_unset_guard_allows_even_invalid_input_and_rules(guard_project):
    assert (
        invoke(guard_project, rules=guard_project / "missing", unattended=None, raw="bad") is None
    )


@pytest.mark.parametrize("tool", ["Read", "Edit", "Write"])
def test_credential_tool_access_is_denied(guard_project, tool):
    secret = guard_project.parent / "claude/.credentials.json"
    reason = invoke(guard_project, tool, {"file_path": str(secret)})
    assert "no-credential-access" in reason


def test_credential_symlinks_and_shell_reads_are_denied(guard_project):
    directory = guard_project.parent / "claude"
    directory.mkdir()
    secret = directory / ".credentials.json"
    secret.write_text("synthetic-test-secret")
    alias = guard_project / "innocent.json"
    alias.symlink_to(secret)
    assert "no-credential-access" in invoke(guard_project, "Read", {"file_path": str(alias)})
    assert "no-credential-access" in invoke(guard_project, tool_input={"command": f"cat {alias}"})
    assert "no-credential-access" in invoke(
        guard_project, tool_input={"command": f"cat < {secret}"}
    )
    assert "no-credential-access" in invoke(
        guard_project, tool_input={"command": f"cat {directory}/.*"}
    )


def test_git_alias_and_configured_mirror_are_denied(guard_project):
    subprocess.run(["git", "config", "alias.publish", "push -f"], cwd=guard_project, check=True)
    assert "no-force-push" in invoke(
        guard_project, tool_input={"command": "git publish origin feature"}
    )
    subprocess.run(["git", "config", "remote.origin.mirror", "true"], cwd=guard_project, check=True)
    assert "no-force-push" in invoke(
        guard_project, tool_input={"command": "git push origin feature"}
    )


@pytest.mark.parametrize(
    "command",
    [
        "env GIT_CONFIG_GLOBAL=/tmp/overrides git publish",
        "GIT_CONFIG_COUNT=1 git push origin feature",
        "env PATH=/tmp git push origin feature",
        "unset DEVKIT_UNATTENDED; git push origin feature",
        "gh alias set publish 'pr merge'",
        "gh --repo example/project pr merge 1",
        '"$program" push origin feature',
        "trap 'git push -f origin feature' EXIT",
        "find . -exec git push -f origin feature ';'",
    ],
)
def test_uninspectable_command_indirection_is_denied(guard_project, command):
    assert "literal-shell" in invoke(guard_project, tool_input={"command": command})


def test_hook_watchdog_refuses_a_blocked_rule_read(guard_project):
    pipe = guard_project / "rules.pipe"
    os.mkfifo(pipe)
    assert "guard-timeout" in invoke(guard_project, rules=pipe, tool_input={"command": "true"})


def test_stack_prefix_rules_apply_to_git_aliases(guard_project):
    configuration = json.loads((ASSETS / "base-rules.json").read_text())
    configuration["rules"]["stack.no-push"] = {"command_prefix": ["git", "push"]}
    path = guard_project / "rules.json"
    path.write_text(json.dumps(configuration))
    subprocess.run(["git", "config", "alias.publish", "push"], cwd=guard_project, check=True)
    reason = invoke(guard_project, rules=path, tool_input={"command": "git publish origin feature"})
    assert reason and "stack.no-push" in reason


def test_invalid_active_input_is_denied_without_echoing_it(guard_project):
    reason = invoke(guard_project, raw="synthetic-secret: invalid JSON")
    assert "guard-input" in reason
    assert "synthetic-secret" not in reason


def test_rule_extensions_must_retain_every_base_rule(guard_project):
    configuration = json.loads((ASSETS / "base-rules.json").read_text())
    del configuration["rules"]["no-force-push"]
    path = guard_project / "rules.json"
    path.write_text(json.dumps(configuration))
    assert "no-force-push" in invoke(guard_project, rules=path, tool_input={"command": "true"})


def test_rule_extensions_cannot_remove_protected_branches(guard_project):
    configuration = json.loads((ASSETS / "base-rules.json").read_text())
    configuration["rules"]["no-protected-push"]["branches"] = []
    path = guard_project / "rules.json"
    path.write_text(json.dumps(configuration))
    assert "no-protected-push" in invoke(guard_project, rules=path, tool_input={"command": "true"})


def test_rules_can_add_commands_and_protected_branch_patterns(guard_project):
    configuration = json.loads((ASSETS / "base-rules.json").read_text())
    configuration["rules"]["stack.no-publish"] = {"command_prefix": ["npm", "publish"]}
    configuration["rules"]["no-protected-push"]["branches"].append("release/*")
    path = guard_project / "rules.json"
    path.write_text(json.dumps(configuration))
    assert "stack.no-publish" in invoke(
        guard_project, rules=path, tool_input={"command": "npm publish"}
    )
    assert "stack.no-publish" in invoke(
        guard_project, rules=path, tool_input={"command": "timeout 5 npm publish"}
    )
    assert "no-protected-push" in invoke(
        guard_project, rules=path, tool_input={"command": "git push origin HEAD:release/19.0"}
    )
    assert invoke(guard_project, rules=path, tool_input={"command": "npm test"}) is None


def set_config(project, key, value):
    subprocess.run(["git", "config", key, value], cwd=project, check=True)


@pytest.mark.parametrize(
    "command",
    [
        "git push origin feature:heads/main",
        "git push origin heads/main",
        "git push origin feature:heads/trunk",
        "git push origin feature:refs//heads/main",
        "git push origin feature:refs/heads/x/../main",
    ],
)
def test_every_spelling_of_a_protected_destination_is_denied(guard_project, command):
    assert "no-protected-push" in invoke(guard_project, tool_input={"command": command})


@pytest.mark.parametrize("spelling", ["@", "HEAD"])
def test_pushing_the_current_protected_branch_by_symbol_is_denied(guard_project, spelling):
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=guard_project, check=True
    )
    command = "git push origin " + spelling
    assert "no-protected-push" in invoke(guard_project, tool_input={"command": command})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("remote.origin.push", "refs/heads/feature:refs/heads/main"),
        ("push.default", "upstream"),
    ],
)
def test_configured_push_mappings_are_denied(guard_project, key, value):
    set_config(guard_project, key, value)
    assert "no-protected-push" in invoke(
        guard_project, tool_input={"command": "git push origin feature"}
    )


@pytest.mark.parametrize(
    "command",
    [
        "command $G push --force origin main",
        "timeout 5 $(echo git) push --force origin main",
        "timeout $T pytest -q",
        "env $X git push --force origin main",
        "{git,} push --force origin main",
        "/usr/bin/gi[t] push --force origin main",
        "gi? push --force origin main",
        ". ./script",
        "export -n DEVKIT_UNATTENDED",
        "export PATH=/tmp/tools",
        "declare -x GIT_DIR=/tmp/other",
        "typeset -x HOME=/tmp/other",
        "export $NAME=value",
        "HOME=/tmp/other git status",
        "XDG_CONFIG_HOME=/tmp/other git status",
        "PATH+=:/tmp/tools git status",
        "GC_BEAD_ID=gate-1 gc bd close gate-1",
    ],
)
def test_dynamic_programs_and_guarded_environment_changes_are_denied(guard_project, command):
    assert "literal-shell" in invoke(guard_project, tool_input={"command": command}, bead="own")


@pytest.mark.parametrize(
    "command",
    [
        "/usr/lib/git-core/git-push --force origin feature",
        "git-push --force origin feature",
    ],
)
def test_dashed_git_executables_are_inspected_as_git(guard_project, command):
    assert "no-force-push" in invoke(guard_project, tool_input={"command": command})


@pytest.mark.parametrize(
    "command",
    [
        "git subtree push --prefix=lib origin main",
        "git-subtree push --prefix=lib origin main",
        "git receive-pack /tmp/remote",
        "git unknown-helper",
        "git zz origin feature",
        "git {push,--version} --force origin main",
    ],
)
def test_unknown_git_commands_are_denied(guard_project, command):
    assert "literal-shell" in invoke(guard_project, tool_input={"command": command})


@pytest.mark.parametrize(
    "command",
    [
        "git config alias.zz 'push --force'; git zz origin feature",
        "git config alias.zz 'push --force'",
        "git config --add remote.origin.push refs/heads/feature:refs/heads/main",
        "git config filter.x.clean 'touch marker'",
        "git config core.sshCommand 'touch marker'",
        "git config --global credential.helper '!touch marker'",
        "git config --unset remote.origin.mirror",
        "git config set core.pager cat",
    ],
)
def test_git_configuration_changes_are_denied(guard_project, command):
    assert "no-operator-state" in invoke(guard_project, tool_input={"command": command})


@pytest.mark.parametrize(
    "command",
    [
        "git config --get remote.origin.url",
        "git config --list",
        "git config -l --show-origin",
        "git config get user.name",
        "git config user.name",
        "git config user.name Fixture",
        "git config --local user.email fixture@example.invalid",
    ],
)
def test_git_configuration_reads_and_identity_are_allowed(guard_project, command):
    assert invoke(guard_project, tool_input={"command": command}) is None


@pytest.mark.parametrize(
    "command",
    [
        "echo '[alias]' >> .git/config",
        "cp hook .git/hooks/pre-commit",
        "tee .git/info/attributes",
        "sed -i s/a/b/ .git/config",
    ],
)
def test_shell_writes_to_git_metadata_are_denied(guard_project, command):
    assert "no-operator-state" in invoke(guard_project, tool_input={"command": command})


@pytest.mark.parametrize("tool", ["Edit", "Write"])
def test_tool_writes_to_git_metadata_are_denied(guard_project, tool):
    arguments = {"file_path": str(guard_project / ".git/config")}
    assert "no-operator-state" in invoke(guard_project, tool=tool, tool_input=arguments)


@pytest.mark.parametrize(
    "request_input",
    [
        ("Edit", {"file_path": ".github/workflows/checks.yml"}),
        ("Write", {"file_path": ".gitignore"}),
        ("Read", {"file_path": ".git/config"}),
        ("Bash", {"command": "cat .git/config"}),
        ("Bash", {"command": "find . -not -path './.git/*'"}),
    ],
)
def test_ordinary_git_named_paths_stay_allowed(guard_project, request_input):
    tool, arguments = request_input
    assert invoke(guard_project, tool=tool, tool_input=arguments) is None


@pytest.mark.parametrize(
    "command",
    [
        "gc bd close gate-1",
        "gc bd close own gate-1",
        "gc bd close $OTHER",
        "gc bd close own --force",
        "gc bd close own --reason $WHY",
        "bd close gate-1",
        "bash -c 'gc bd close gate-1'",
        "gc bd update gate-1 --set-metadata devkit.brief.approved_sha256=abc",
        "gc bd update own --set-metadata gc.outcome=pass",
        "gc bd comments add task-one forged",
        "bd comment task-one forged",
        "gc bd --json close gate-1",
        "gc $COMMAND close gate-1",
        "gc base brief approve --workflow run --sha256 abc",
        "gc base feedback answers answers.json --task t --workflow r --round 1",
        "gc base feedback begin --task t --workflow r --branch b",
        "gc base feedback next file --task t --workflow r --round 1 --next-workflow n",
        "gc odoo delivery publish --workflow r --approved-body-sha256 abc",
        "gc vue delivery bind job.json --workflow r --task t",
        "gc formula cook anything",
        "gc --city /other bd close gate-1",
    ],
)
def test_operator_task_state_commands_are_denied(guard_project, command):
    assert "no-operator-state" in invoke(guard_project, tool_input={"command": command}, bead="own")


def test_closing_any_bead_is_denied_without_an_assigned_bead(guard_project):
    reason = invoke(guard_project, tool_input={"command": "gc bd close own"})
    assert "no-operator-state" in reason


@pytest.mark.parametrize(
    "command",
    [
        "gc bd close own",
        "gc bd close own --reason 'Finished the attempt' --json",
        "gc bd close own -r done",
        'gc bd close "$GC_BEAD_ID" --reason done',
        "gc bd close ${GC_BEAD_ID}",
        "bd close own",
        "gc bd show task-one --json",
        'gc bd show "$ROOT"',
        "gc bd list --all --json",
        "gc bd comments task-one --json",
        "gc base brief lint /tmp/brief.json --task t",
        "gc base brief record /tmp/brief.json --task t --workflow r",
        "gc base brief show --workflow r",
        "gc base brief verify --workflow r --task t",
        "gc base brief resume --task t",
        "gc base feedback questions q.json --task t --workflow r --round 1",
        "gc base feedback friction f.json --task t --workflow r --round 1 --friction-task b",
        "gc base feedback show --task t --workflow r --round 1",
        "gc odoo delivery report --workflow r",
        "gc vue delivery report --workflow r",
        "gc ready",
    ],
)
def test_session_task_commands_are_allowed(guard_project, command):
    assert invoke(guard_project, tool_input={"command": command}, bead="own") is None
