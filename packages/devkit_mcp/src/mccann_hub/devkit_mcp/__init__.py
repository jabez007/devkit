"""Optional local stdio presentation of authorized devkit commands."""

import argparse
import json
from dataclasses import asdict
from functools import partial
from pathlib import Path
from threading import Event
from typing import Any

import anyio
from mccann_hub.devkit.app import create_service
from mccann_hub.devkit.contracts import CommandResult, DevkitError, JSONObject
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations


def _execute(project: Path, name: str, arguments: JSONObject, cancel: Event) -> JSONObject:
    try:
        service = create_service(project)
        return service.execute(name, arguments, surface="mcp", cancellation=cancel)
    except (DevkitError, OSError, ValueError):
        return {
            "result": asdict(
                CommandResult(
                    "blocked",
                    "Project configuration or operator trust is invalid",
                    reason="ACTIVATION_FAILED",
                )
            )
        }


def create_server(project: Path) -> Server[Any]:
    server: Server[Any] = Server("mccann_hub.devkit_mcp", version="0.1.0")
    lock = anyio.Lock()

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[Tool]:
        async with lock:
            return tools()

    def tools() -> list[Tool]:
        try:
            service = create_service(project)
            specs = service.allowed("mcp")
        except (DevkitError, OSError, ValueError):
            return []
        return [
            Tool(
                name=spec.id,
                description=spec.description,
                inputSchema=spec.input_schema,
                annotations=ToolAnnotations(
                    readOnlyHint=False,  # Every invocation persists an evidence bundle.
                    destructiveHint=bool(spec.effects & {"write_fs", "network_write"}),
                    idempotentHint=False,
                    openWorldHint=bool(spec.effects & {"network_read", "network_write"}),
                ),
            )
            for spec in specs
        ]

    @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: JSONObject) -> CallToolResult:
        async with lock:
            cancelled, finished = Event(), Event()

            def execute() -> JSONObject:
                try:
                    return _execute(project, name, arguments, cancelled)
                finally:
                    finished.set()

            try:
                envelope = await anyio.to_thread.run_sync(execute, abandon_on_cancel=True)
            except anyio.get_cancelled_exc_class():
                cancelled.set()
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(partial(finished.wait, 3))
                raise
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(envelope))],
                structuredContent=envelope,
                isError=envelope["result"]["status"] != "success",
            )

    return server


async def serve(project: Path) -> None:
    server = create_server(project)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(prog="devkit-mcp")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    anyio.run(serve, args.project)
