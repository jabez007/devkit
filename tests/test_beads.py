"""Exercise Beads commands through public invocation, CLI and MCP interfaces."""

import json
import os
import subprocess
from pathlib import Path
from threading import Event, Timer

import pytest
from devkit.app import create_service

from tests.beads_helpers import REF, SCOPE, configure


def test_read_commands_and_persisted_evidence(beads_project):
    service = create_service(beads_project)
    assert service.execute("core.doctor")["result"]["status"] == "success"
    for command, args, key in (
        ("beads.workspace", {}, "workspace"),
        ("beads.item.show", {"ref": REF}, "item"),
        ("beads.ready", {"limit": 1}, "items"),
        ("beads.dependencies", {"ref": REF}, "dependencies"),
    ):
        result = service.execute(command, args)
        assert result["result"]["status"] == "success", result
        data = result["result"]["data"]
        assert key in data
        assert data["workspace"]["project_id"] == SCOPE
        assert json.loads(Path(result["evidence_path"]).read_text())["result"] == result["result"]
    assert data["dependencies"][0]["ref"] == f"beads:{SCOPE}:demo-2"
    assert data["dependencies"][0]["dependency_type"] == "blocks"


@pytest.mark.parametrize(
    "settings,reason",
    [
        ({"version": "1.2.2"}, "UNSUPPORTED_BEADS_VERSION"),
        ({"mode": "malformed"}, "INVALID_TOOL_OUTPUT"),
        ({"mode": "oversized"}, "OUTPUT_LIMIT"),
        ({"mode": "unavailable"}, "BEADS_UNAVAILABLE"),
        ({"context": {"project_id": None}}, "INVALID_TOOL_OUTPUT"),
        ({"context": {"dolt_mode": "server"}}, "UNSUPPORTED_BEADS_WORKSPACE"),
        ({"context": {"is_redirected": True}}, "UNSUPPORTED_BEADS_WORKSPACE"),
        ({"context": {"is_worktree": True}}, "UNSUPPORTED_BEADS_WORKSPACE"),
        ({"context": {"repo_root": "/another/project"}}, "WORKSPACE_MISMATCH"),
        ({"show": {}}, "INVALID_TOOL_OUTPUT"),
        ({"show": [{"id": "--help"}]}, "INVALID_TOOL_OUTPUT"),
        ({"show": []}, "INVALID_TOOL_OUTPUT"),
    ],
)
def test_unavailable_or_untrusted_responses(beads_project, settings, reason):
    configure(beads_project, **settings)
    result = create_service(beads_project).execute("beads.item.show", {"ref": REF})
    # A prerequisite failure retains the diagnostic in its child evidence.
    result = result["result"]
    if "checks" in result["data"]:
        result = result["data"]["checks"][0]["result"]
    assert result["reason"] == reason
    assert result["status"] in {"blocked", "error"}


def test_invalid_input_and_policy_denial_never_start_beads(beads_project):
    service = create_service(beads_project)
    for args in ({"limit": 0}, {"limit": 101}, {"limit": True}):
        assert service.execute("beads.ready", args)["result"]["reason"] == "INVALID_INPUT"
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text('[trusted_plugins]\ndevkit-beads="0.1.0"\n')
    assert service.execute("beads.ready")["result"]["reason"] == "DENIED"
    assert not (beads_project / "calls.jsonl").exists()


def test_missing_tool_workspace_and_scope(beads_project, monkeypatch):
    service = create_service(beads_project)
    other = REF.replace(SCOPE, "00000000-0000-0000-0000-000000000000")
    assert (
        service.execute("beads.item.show", {"ref": other})["result"]["reason"]
        == "WORKSPACE_MISMATCH"
    )
    monkeypatch.setenv("PATH", "/not-installed")
    assert service.execute("beads.workspace")["result"]["reason"] == "MISSING_TOOL"
    (beads_project / ".beads").rmdir()
    assert service.execute("beads.workspace")["result"]["reason"] == "BEADS_NOT_INITIALIZED"
    (beads_project / ".beads").symlink_to(beads_project.parent, target_is_directory=True)
    assert service.execute("beads.workspace")["result"]["reason"] == "BEADS_NOT_INITIALIZED"


def test_cancellation_and_timeout(beads_project):
    configure(beads_project, mode="sleep")
    cancellation = Event()
    timer = Timer(0.2, cancellation.set)
    timer.start()
    try:
        result = create_service(beads_project).execute("beads.workspace", cancellation=cancellation)
    finally:
        timer.join()
    assert result["result"]["status"] == "cancelled"
    result = create_service(beads_project, timeout=0.1).execute("beads.workspace")
    assert result["result"]["reason"] == "TIMEOUT"


def test_cli_python_mcp_parity(beads_project):
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    expected = create_service(beads_project).execute("beads.item.show", {"ref": REF})["result"]
    cli = subprocess.run(
        [
            str(Path(".venv/bin/devkit").resolve()),
            "--project",
            str(beads_project),
            "--json",
            "run",
            "beads.item.show",
            "--args",
            json.dumps({"ref": REF}),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(cli.stdout)["result"] == expected

    async def check():
        params = StdioServerParameters(
            command=str(Path(".venv/bin/devkit-mcp").resolve()),
            args=["--project", str(beads_project)],
            env=dict(os.environ),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("beads.item.show", {"ref": REF})
                assert result.structuredContent["result"] == expected
                bad = await session.call_tool("beads.item.show", {"ref": "demo-1"})
                assert bad.structuredContent["result"]["reason"] == "INVALID_INPUT"

    anyio.run(check)
