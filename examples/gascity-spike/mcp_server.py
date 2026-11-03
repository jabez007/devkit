"""Project-local MCP probe used only by the disposable qualification session."""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

server = FastMCP("Devkit spike")


@server.tool()
def marker() -> str:
    """Confirm this project's MCP server was called by the live session."""
    (Path.cwd() / ".spike/mcp-observed").write_text("DEVKIT_PROJECT_MCP_OK\n")
    return "DEVKIT_PROJECT_MCP_OK"


if __name__ == "__main__":
    server.run(transport="stdio")
