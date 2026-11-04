"""Shared one-shot launcher behavior through its executable interface."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "integrations/gascity/base"


@pytest.fixture
def session(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    city_settings = tmp_path / "settings.json"
    city_settings.write_text('{"hooks":{"SessionStart":[],"UserPromptSubmit":[]}}')
    mcp = project / ".mcp.json"
    mcp.write_text('{"mcpServers":{}}')
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Complete the approved fixture task.")
    config = tmp_path / "session.json"
    data = dict(
        project=str(project),
        city_settings=str(city_settings),
        mcp_config=str(mcp),
        prompt_file=str(prompt),
        allowed_tools=["Read", "Bash(git status *)"],
        artifacts=str(tmp_path / "artifacts"),
    )
    config.write_text(json.dumps(data))
    binary = tmp_path / "claude"
    binary.write_text(
        f"#!{sys.executable}\nimport json, os, sys\n"
        "print(json.dumps(dict(arguments=sys.argv[1:], cwd=os.getcwd(), "
        "api_key='ANTHROPIC_API_KEY' in os.environ, "
        "auth_token='ANTHROPIC_AUTH_TOKEN' in os.environ, "
        "unattended=os.environ.get('DEVKIT_UNATTENDED'))))\n"
        "sys.exit(int(os.environ.get('FAKE_EXIT_CODE', '0')))\n"
    )
    binary.chmod(0o700)
    return config, data, binary


def launch(session, **environment):
    config, data, binary = session
    result = subprocess.run(
        [sys.executable, str(BASE / "assets/launch.py")],
        env={
            **os.environ,
            "PATH": str(binary.parent) + os.pathsep + os.environ["PATH"],
            "DEVKIT_SESSION_CONFIG": str(config),
            "ANTHROPIC_API_KEY": "synthetic",
            "ANTHROPIC_AUTH_TOKEN": "synthetic",
            **environment,
        },
        text=True,
        capture_output=True,
        timeout=10,
    )
    return result


def test_base_launcher_uses_explicit_settings_and_subscription(session):
    result = launch(session)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "DEVKIT_SESSION_READY"
    _, data, _ = session
    observed = json.loads((Path(data["artifacts"]) / "agent.jsonl").read_text())
    arguments = observed["arguments"]
    assert arguments[0:2] == ["--print", "Complete the approved fixture task."]
    assert arguments[arguments.index("--settings") + 1] == data["city_settings"]
    assert arguments[arguments.index("--mcp-config") + 1] == data["mcp_config"]
    assert "--strict-mcp-config" in arguments and "--bare" not in arguments
    assert arguments[arguments.index("--setting-sources") + 1] == "project"
    assert observed["cwd"] == data["project"]
    assert not observed["api_key"] and not observed["auth_token"]
    assert observed["unattended"] == "1"
    assert (Path(data["artifacts"]) / "agent.exit").read_text() == "0"


def test_base_launcher_retains_client_exit_status(session):
    result = launch(session, FAKE_EXIT_CODE="7")
    assert result.returncode == 7, result.stderr
    assert (Path(session[1]["artifacts"]) / "agent.exit").read_text() == "7"


@pytest.mark.parametrize(
    "change",
    [
        {"city_settings": "/nonexistent/native-settings.json"},
        {"mcp_config": "/nonexistent/project-mcp.json"},
        {"allowed_tools": []},
        {"additional_flags": ["--bare"]},
        {"project": "relative/project"},
    ],
)
def test_base_launcher_refuses_incomplete_or_extended_config_before_readiness(session, change):
    path, data, _ = session
    path.write_text(json.dumps({**data, **change}))
    result = launch(session)
    assert result.returncode != 0
    assert "DEVKIT_SESSION_READY" not in result.stdout


def test_base_launcher_cannot_overwrite_previous_session_evidence(session):
    assert launch(session).returncode == 0
    artifact = Path(session[1]["artifacts"]) / "agent.jsonl"
    previous = artifact.read_bytes()
    rerun = launch(session)
    assert rerun.returncode != 0 and "DEVKIT_SESSION_READY" not in rerun.stdout
    assert artifact.read_bytes() == previous


def test_base_launcher_refuses_oversized_prompt(session):
    Path(session[1]["prompt_file"]).write_bytes(b"x" * 1_000_001)
    result = launch(session)
    assert result.returncode != 0 and "DEVKIT_SESSION_READY" not in result.stdout
