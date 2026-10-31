"""Build a renamed template outside the repository and exercise its full lifecycle."""

import json
import os
import shutil
import sys
from pathlib import Path

from check_wheels import ROOT, absent, cli, install, policy, run


def build(root, wheels):
    source = root / "independent-author"
    shutil.copytree(
        ROOT / "examples/plugin", source, ignore=shutil.ignore_patterns("dist", "__pycache__")
    )
    metadata = source / "pyproject.toml"
    metadata.write_text(metadata.read_text().replace("example", "textcheck"))
    package = source / "src/devkit_textcheck"
    (source / "src/devkit_example").rename(package)
    shutil.copyfile(ROOT / "examples/readme_specialization.py", package / "__init__.py")
    run("uv", "build", "--out-dir", str(wheels), cwd=source)


def parity(root, project, env, expected):
    code = """
import anyio, json, os, sys
from pathlib import Path
from devkit.app import create_service
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
project, expected = Path(sys.argv[1]), json.loads(sys.argv[2])
assert create_service(project).execute("textcheck.readme")["result"] == expected
async def check():
    params = StdioServerParameters(
        command=sys.argv[3], args=["--project",str(project)], env=dict(os.environ))
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            response = await session.call_tool("textcheck.readme",{})
            envelope = response.structuredContent
            assert envelope["result"] == expected
            assert json.loads(Path(envelope["evidence_path"]).read_text())["result"] == expected
anyio.run(check)
"""
    run(
        str(root / "venv/bin/python"),
        "-c",
        code,
        str(project),
        json.dumps(expected),
        str(root / "venv/bin/devkit-mcp"),
        cwd=project,
        env=env,
    )


def main():
    root, wheels, constraints = map(Path, sys.argv[1:4])
    root.mkdir()
    build(root, wheels)
    project, env = install(
        root, wheels, ["devkit", "devkit_textcheck", "devkit_example", "devkit_mcp"], constraints
    )
    absent(root, project, env, ["devkit_go", "devkit_odoo", "devkit_beads", "odoo"])
    (project / "README.md").write_text("# Project\nUseful verification.\n")
    # Discovery requires no trust or project activation.
    discovered = cli(root, project, env, "plugins")["result"]["data"]["plugins"]
    assert any(plugin["id"] == "textcheck" for plugin in discovered), discovered
    (project / "devkit.toml").write_text('plugins=["textcheck","example"]')
    cli(root, project, env, "run", "textcheck.readme", expected=3)
    policy(
        root,
        project,
        ["textcheck", "example"],
        {"textcheck.readme": ["read_fs"], "example.greet": []},
    )
    result = cli(root, project, env, "run", "textcheck.readme")
    assert result["result"]["data"] == {"lines": 2, "trailing_whitespace_lines": []}
    parity(root, project, env, result["result"])
    (project / "README.md").write_text("# Project  \nUseful verification.\n")
    failed = cli(root, project, env, "run", "textcheck.readme", expected=1)
    assert failed["result"]["data"]["trailing_whitespace_lines"] == [1]
    parity(root, project, env, failed["result"])
    (project / "README.md").unlink()
    os.mkfifo(project / "README.md")
    assert (
        cli(root, project, env, "run", "textcheck.readme", expected=2)["result"]["reason"]
        == "UNSAFE_PATH"
    )
    (project / "README.md").unlink()
    # Deny an installed, trusted plugin independently of its activation.
    policy(root, project, ["textcheck", "example"], {"example.greet": []})
    assert (
        cli(root, project, env, "run", "textcheck.readme", expected=2)["result"]["reason"]
        == "DENIED"
    )
    (project / "devkit.toml").write_text('plugins=["example"]')
    cli(root, project, env, "run", "example.greet", "--args", '{"name":"Dev"}')
    run("uv", "pip", "uninstall", "--python", str(root / "venv/bin/python"), "devkit-textcheck")
    absent(root, project, env, ["devkit_textcheck"])
    cli(root, project, env, "run", "example.greet", "--args", '{"name":"Dev"}')
    shown = cli(root, project, env, "runs", "show", result["run_id"])["result"]["data"]
    assert shown["run"]["result"] == result["result"]
    print(
        "PASS: renamed third-party template, wheel discovery/trust/authorization, "
        "three surfaces, removal"
    )


if __name__ == "__main__":
    main()
