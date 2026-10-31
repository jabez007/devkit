import json
import os
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import anyio
import pytest
from devkit.app import create_service
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification, JSONRPCRequest


def parameters(project):
    return StdioServerParameters(
        command=str(Path(".venv/bin/devkit-mcp").resolve()),
        args=["--project", str(project)],
        env=dict(os.environ),
    )


@pytest.mark.parametrize(
    "mode,arguments,exit_code",
    [
        ("unknown", {}, 0),
        ("unknown", {"strict_dependencies": True}, 2),
        ("unknown", {"inventory": {"complete": True}}, 1),
        ("invalid", {}, 1),
        ("cycle", {}, 1),
        ("cycle", {"module": "example", "strict_dependencies": True}, 0),
        ("resolved", {"strict_dependencies": True}, 0),
        ("xml_valid", {}, 0),
        ("xml_malformed", {}, 1),
        ("xml_dtd", {}, 2),
        ("csv_access", {}, 0),
        ("csv_empty", {}, 1),
        ("csv_unsupported", {}, 2),
    ],
)
def test_stdio_parity_and_denials(odoo_project, mode, arguments, exit_code):
    project, module = odoo_project
    if mode == "invalid":
        (module / "__manifest__.py").write_text("{'name': 'Bad', 'depends': ['../escape']}")
    if mode in {"resolved", "cycle"}:
        base = project / "addons/base"
        base.mkdir()
        (base / "__manifest__.py").write_text(
            repr({"name": "Base", "depends": ["example"] if mode == "cycle" else []})
        )
    if mode.startswith(("xml_", "csv_")):
        addon = "acme_csv" if mode.startswith("csv_") else "acme_xml"
        fixture = Path("tests/fixtures/odoo") / mode / "addons" / addon
        shutil.copytree(fixture, module, dirs_exist_ok=True)
    python_result = create_service(project).execute("odoo.module.validate", arguments)["result"]
    cli = subprocess.run(
        [
            str(Path(".venv/bin/devkit").resolve()),
            "--project",
            str(project),
            "--json",
            "run",
            "odoo.module.validate",
            "--args",
            json.dumps(arguments),
        ],
        capture_output=True,
        text=True,
    )
    assert cli.returncode == exit_code
    assert json.loads(cli.stdout)["result"] == python_result

    async def exercise():
        async with stdio_client(parameters(project)) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=10)
            ) as session:
                initialized = await session.initialize()
                assert initialized.protocolVersion == "2025-11-25"
                tools = await session.list_tools()
                assert [tool.name for tool in tools.tools] == ["odoo.module.validate"]
                result = await session.call_tool("odoo.module.validate", arguments)
                assert bool(result.isError) == (exit_code != 0)
                assert result.structuredContent["result"] == python_result
                malformed = await session.call_tool("odoo.module.validate", {"unknown": True})
                assert malformed.isError
                assert malformed.structuredContent["result"]["reason"] == "INVALID_INPUT"
                denied = await session.call_tool("go.test", {})
                assert denied.isError
                assert denied.structuredContent["result"]["reason"] == "DENIED"
                unknown = await session.call_tool("missing.command", {})
                assert unknown.isError
                assert unknown.structuredContent["result"]["reason"] == "UNKNOWN_COMMAND"
                policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
                policy.write_text('deny=["odoo.module.validate"]')
                assert not (await session.list_tools()).tools
                revoked = await session.call_tool("odoo.module.validate", {})
                assert revoked.isError

    anyio.run(exercise)


def test_stdio_cancellation_persists_cancelled_evidence(go_project):
    project = go_project
    (project / "wait_test.go").write_text(
        'package check\nimport ("testing"; "time"; "os")\n'
        'func TestWait(t *testing.T) { os.WriteFile("started", []byte("ready"), 0600); '
        "time.Sleep(30*time.Second) }\n"
    )
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(policy.read_text().replace('["python"]', '["python","mcp"]'))

    async def exercise():
        async with stdio_client(parameters(project)) as (read, write):
            with anyio.fail_after(30):
                await write.send(
                    SessionMessage(
                        JSONRPCMessage(
                            JSONRPCRequest(
                                jsonrpc="2.0",
                                id="init",
                                method="initialize",
                                params={
                                    "protocolVersion": "2025-11-25",
                                    "capabilities": {},
                                    "clientInfo": {"name": "cancel-test", "version": "1"},
                                },
                            )
                        )
                    )
                )
                await read.receive()
                await write.send(
                    SessionMessage(
                        JSONRPCMessage(
                            JSONRPCNotification(
                                jsonrpc="2.0",
                                method="notifications/initialized",
                            )
                        )
                    )
                )
                await write.send(
                    SessionMessage(
                        JSONRPCMessage(
                            JSONRPCRequest(
                                jsonrpc="2.0",
                                id="cancel-me",
                                method="tools/call",
                                params={"name": "go.test", "arguments": {}},
                            )
                        )
                    )
                )
                while not (project / "started").exists():
                    await anyio.sleep(0.05)
                await write.send(
                    SessionMessage(
                        JSONRPCMessage(
                            JSONRPCNotification(
                                jsonrpc="2.0",
                                method="notifications/cancelled",
                                params={"requestId": "cancel-me", "reason": "test cancellation"},
                            )
                        )
                    )
                )
                evidence = Path(os.environ["XDG_STATE_HOME"]) / "devkit/runs"
                while not list(evidence.glob("*/result.json")):
                    await anyio.sleep(0.05)
                result = json.loads(next(evidence.glob("*/result.json")).read_text())
                assert result["result"]["status"] == "cancelled"
                response = await read.receive()
                assert response.message.root.id == "cancel-me"

    anyio.run(exercise)
