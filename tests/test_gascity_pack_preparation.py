"""Operator preparation of readonly assets, branch policy, and native runtime settings."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "integrations/gascity/base"
GUARD = ROOT / "integrations/unattended"


@pytest.fixture
def deployment(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    claude = project / ".claude"
    claude.mkdir()
    original = {
        "includeCoAuthoredBy": False,
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [{"type": "command", "command": "existing-project-hook"}],
                }
            ]
        },
    }
    (claude / "settings.json").write_text(json.dumps(original))
    for name, text in [
        ("native.json", '{"hooks":{"SessionStart":[],"UserPromptSubmit":[]}}'),
        ("prompt.md", "Complete the approved fixture task."),
        ("credentials.json", "synthetic credential fixture"),
        ("claude", "fixture executable"),
        ("gc-session-docker", "fixture runtime"),
    ]:
        (tmp_path / name).write_text(text)
    (project / ".mcp.json").write_text('{"mcpServers":{}}')
    session = tmp_path / "session.json"
    session.write_text(
        json.dumps(
            dict(
                project=str(project),
                city_settings=str(tmp_path / "native.json"),
                mcp_config=str(project / ".mcp.json"),
                prompt_file=str(tmp_path / "prompt.md"),
                allowed_tools=["Read"],
                artifacts=str(tmp_path / "artifacts"),
            )
        )
    )
    config = dict(
        session=str(session),
        claude=str(tmp_path / "claude"),
        credentials=str(tmp_path / "credentials.json"),
        config_dir="/home/worker/.claude",
        runtime=str(tmp_path / "gc-session-docker"),
        image="fixture:tested",
        user="1000:1000",
        network="host",
        packs=[str(BASE)],
        readonly=[],
        writable=[],
        default_branch="trunk",
        protected_branches=["release/*"],
    )
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(config))
    return path, config, project, original


def prepare(deployment, **changes):
    path, config, _, _ = deployment
    path.write_text(json.dumps({**config, **changes}))
    return subprocess.run(
        [sys.executable, str(BASE / "assets/prepare.py"), str(path)],
        text=True,
        capture_output=True,
        timeout=10,
    )


def settings(project):
    return json.loads((project / ".claude/settings.json").read_text())


def test_preparation_installs_base_rules_preserves_settings_and_is_idempotent(deployment):
    _, _, project, original = deployment
    first = prepare(deployment)
    assert first.returncode == 0, first.stderr
    configured = settings(project)
    assert configured["includeCoAuthoredBy"] is False
    assert original["hooks"]["PreToolUse"][0] in configured["hooks"]["PreToolUse"]
    assert len(configured["hooks"]["PreToolUse"]) == 2
    rules = json.loads((project / ".claude/devkit-unattended-rules.json").read_text())["rules"]
    base = json.loads((GUARD / "base-rules.json").read_text())["rules"]
    assert set(base) <= set(rules)
    assert {"main", "master", "trunk", "release/*"} <= set(rules["no-protected-push"]["branches"])
    assert prepare(deployment).returncode == 0
    assert settings(project) == configured


def test_preparation_mounts_native_sources_settings_and_only_selected_credential(deployment):
    _, config, project, _ = deployment
    result = prepare(deployment)
    assert result.returncode == 0, result.stderr
    prepared = json.loads(result.stdout)
    assert prepared["session_provider"] == "exec:" + config["runtime"]
    env = prepared["workspace_env"]
    assert env["GC_DOCKER_HOME_MOUNT"] == "false"
    assert env["DEVKIT_UNATTENDED"] == "1"
    assert env["DEVKIT_PACK_BASE"] == str(BASE)
    mounts = env["GC_DOCKER_EXTRA"].split()
    for path in [
        str(BASE),
        str(GUARD),
        str(project / ".claude"),
        config["session"],
        str(project / ".mcp.json"),
    ]:
        assert f"--mount=type=bind,src={path},dst={path},readonly" in mounts
    assert (
        f"--mount=type=bind,src={config['credentials']},"
        "dst=/home/worker/.claude/.credentials.json,readonly"
    ) in mounts
    assert not any(f"src={Path.home()}," in value or "docker.sock" in value for value in mounts)


@pytest.mark.parametrize(
    "changes",
    [
        {"default_branch": ""},
        {"protected_branches": None},
        {"readonly": ["/var/run/docker.sock"]},
        {"writable": [str(Path.home())]},
        {"writable": ["/"]},
        {"config_dir": "relative"},
        {"image": "fixture --privileged"},
        {"session": "/tmp/missing session.json"},
    ],
)
def test_preparation_rejects_unsafe_or_missing_inputs_before_modifying_settings(
    deployment, changes
):
    original = settings(deployment[2])
    result = prepare(deployment, **changes)
    assert result.returncode != 0
    assert settings(deployment[2]) == original
    assert not (deployment[2] / ".claude/devkit-unattended-rules.json").exists()


def test_preparation_cannot_weaken_base_guard_rules(deployment, tmp_path):
    weakened = json.loads((GUARD / "base-rules.json").read_text())
    del weakened["rules"]["no-force-push"]
    path = tmp_path / "weakened.json"
    path.write_text(json.dumps(weakened))
    result = prepare(deployment, stack_rules=str(path))
    assert result.returncode != 0
    assert settings(deployment[2]) == deployment[3]


def test_prepared_guard_really_enforces_the_operator_default_branch(deployment):
    assert prepare(deployment).returncode == 0
    project = deployment[2]
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch", "feature", str(project)], check=True
    )
    subprocess.run(
        ["git", "-C", str(project), "remote", "add", "origin", "/tmp/unused-remote"], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            "refs/remotes/origin/feature",
        ],
        check=True,
    )
    rule_file = project / ".claude/devkit-unattended-rules.json"
    result = subprocess.run(
        [sys.executable, str(GUARD / "guard.py"), "--rules", str(rule_file)],
        env={**os.environ, "DEVKIT_UNATTENDED": "1"},
        text=True,
        capture_output=True,
        input=json.dumps(
            dict(
                tool_name="Bash",
                tool_input={"command": "git push origin HEAD:trunk"},
                cwd=str(project),
            )
        ),
        timeout=10,
    )
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "no-protected-push" in decision["permissionDecisionReason"]
