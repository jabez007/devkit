"""Public CLI procedures and the standalone plugin's checkout selection."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import validate
from mccann_hub.devkit_beads import register

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "integrations/claude-code"


def test_documented_beads_arguments_match_public_command_schemas():
    commands = {command.id: command for command in register().commands}
    examples = (PLUGIN / "references/work-items.md").read_text()
    examples = examples.replace("PROJECT_UUID", "00000000-0000-4000-8000-000000000001")
    examples = examples.replace("RUN_UUID", "00000000-0000-4000-8000-000000000002")
    examples = examples.replace("ISSUE_ID", "test-123")
    checked = set()
    for line in examples.splitlines():
        if line.startswith("devkit ") and " --args " in line:
            args = shlex.split(line)
            command = args[args.index("run") + 1]
            validate(json.loads(args[args.index("--args") + 1]), commands[command].input_schema)
            checked.add(command)
    assert checked == set(commands) - {"beads.workspace"}


@pytest.fixture
def bundle(tmp_path):
    target = tmp_path / "standalone plugin"
    shutil.copytree(PLUGIN, target)
    return target


def resolve(bundle, cwd, *args, env=None):
    return subprocess.run(
        [sys.executable, str(bundle / "scripts/checkout.py"), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def git(project, *args):
    return subprocess.run(
        ["git", "-C", str(project), *args], check=True, capture_output=True, text=True
    )


def test_standalone_bundle_has_no_automatic_execution_or_grants(bundle):
    manifest = json.loads((bundle / ".claude-plugin/plugin.json").read_text())
    assert manifest["name"] == "mccann-hub-devkit"
    assert manifest["license"] == "GPL-3.0-or-later"
    assert (bundle / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert not {"hooks", "mcpServers", "agents"}.intersection(manifest)
    assert not any((bundle / path).exists() for path in (".mcp.json", "hooks", "agents"))
    skills = list((bundle / "skills").glob("*/SKILL.md"))
    assert len(skills) == 2
    for skill in skills:
        text = skill.read_text()
        frontmatter = text.split("---", 2)[1]
        assert "allowed-tools:" not in frontmatter
        assert "context: fork" not in frontmatter
        assert "!`" not in text
        assert len(text.split()) < 450
    assert (bundle / "references/verification.md").is_file()
    assert (bundle / "references/work-items.md").is_file()


def test_checkout_preserves_each_linked_worktree_and_ignores_git_overrides(
    bundle, tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "--quiet")
    git(
        main,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "fixture",
    )
    roots = [main]
    for name in ("first", "second"):
        worktree = tmp_path / name
        git(main, "worktree", "add", "-b", name, str(worktree))
        roots.append(worktree)
    for root in roots:
        nested = root / "nested dir"
        nested.mkdir()
        result = resolve(
            bundle,
            nested,
            env={**os.environ, "GIT_DIR": str(main / ".git"), "GIT_WORK_TREE": str(main)},
        )
        assert result.returncode == 0, result.stderr
        assert Path(result.stdout.strip()) == root
        envelope = invoke(Path(result.stdout.strip()), "doctor")
        assert envelope["project_root"] == str(root)
        rows = invoke(root, "runs", "list")["result"]["data"]["runs"]
        assert [row["run_id"] for row in rows] == [envelope["run_id"]]


def test_explicit_non_git_subproject_and_symlink(bundle, tmp_path):
    project = tmp_path / "non git project"
    project.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(project, target_is_directory=True)
    assert resolve(bundle, tmp_path).returncode == 2
    selected = resolve(bundle, tmp_path, "--project", str(alias))
    assert selected.returncode == 0
    assert selected.stdout.strip() == str(project)


@pytest.mark.parametrize("kind", ["missing", "file", "no-git"])
def test_checkout_failure_is_actionable(bundle, tmp_path, kind):
    args = []
    env = dict(os.environ)
    if kind == "no-git":
        env["PATH"] = str(tmp_path / "empty-bin")
    else:
        path = tmp_path / kind
        if kind == "file":
            path.write_text("not a directory")
        args = ["--project", str(path)]
    result = resolve(bundle, tmp_path, *args, env=env)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "Select an existing --project directory" in result.stderr
    assert "Traceback" not in result.stderr


def invoke(project, *args, expected=0):
    result = subprocess.run(
        [str(ROOT / ".venv/bin/devkit"), "--project", str(project), "--json", *args],
        capture_output=True,
        text=True,
        cwd=project,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_documented_diagnostics_and_evidence_after_bundle_removal(bundle, odoo_project):
    project, module = odoo_project
    config = project / "devkit.toml"
    config.write_text('plugins=["not-installed"]')
    assert invoke(project, "plugins", "list", "--details")["result"]["data"]["missing"]
    assert (
        invoke(project, "plugins", "validate", expected=2)["result"]["reason"] == "PLUGIN_SELECTION"
    )
    config.write_text('plugins=["odoo"]\n[profiles]\nverify=["odoo.manifests"]\n')
    passed = invoke(project, "check", "verify")
    blocked = invoke(
        project, "run", "odoo.module.validate", "--args", '{"strict_dependencies":true}', expected=2
    )
    assert blocked["result"]["reason"] == "INCOMPLETE_INVENTORY"
    module.joinpath("__manifest__.py").write_text("not a literal")
    failed = invoke(project, "check", "verify", expected=1)
    invoke(project, "check", "no-such-profile", expected=3)
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text('[trusted_plugins]\nmccann-hub-devkit-odoo="0.5.0"\n')
    assert (
        invoke(project, "run", "odoo.module.validate", expected=2)["result"]["reason"] == "DENIED"
    )
    policy.write_text("")
    assert (
        invoke(project, "plugins", "validate", expected=2)["result"]["reason"] == "UNTRUSTED_PLUGIN"
    )
    shutil.rmtree(bundle)
    config.write_text("plugins=[]")
    for envelope in (passed, blocked, failed):
        shown = invoke(project, "runs", "show", envelope["run_id"])
        assert shown["result"]["data"]["run"] == {
            key: value for key, value in envelope.items() if key != "evidence_path"
        }
    invoke(project, "doctor")


def test_missing_cli_and_mcp_are_detected_without_installation(bundle, tmp_path):
    env = {**os.environ, "PATH": str(tmp_path / "empty-bin")}
    for executable in ("devkit", "devkit-mcp"):
        result = subprocess.run(
            ["/bin/sh", "-c", f"command -v {executable}"], env=env, capture_output=True
        )
        assert result.returncode != 0
    # Explicit project selection has no Git, Devkit, MCP, or Claude dependency.
    assert resolve(bundle, tmp_path, "--project", str(tmp_path), env=env).returncode == 0
