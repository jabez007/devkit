"""Build a renamed template outside the repository and exercise its full lifecycle."""

import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from check_wheels import ROOT, absent, cli, install, policy, run


def build(root, wheels):
    source = root / "independent-author"
    shutil.copytree(
        ROOT / "examples/plugin",
        source,
        ignore=shutil.ignore_patterns("dist", "__pycache__", ".pytest_cache", ".venv"),
    )
    for path in source.rglob("*"):
        if path.suffix in {".py", ".toml", ".md"}:
            path.write_text(
                path.read_text()
                .replace("mccann-hub-devkit-example", "author-demo-textcheck")
                .replace("mccann_hub.devkit_example", "author_demo.textcheck")
                .replace("src/mccann_hub/devkit_example", "src/author_demo/textcheck")
                .replace('packages = ["src/mccann_hub"]', 'packages = ["src/author_demo"]')
                .replace("example", "textcheck")
            )
    package = source / "src/author_demo/textcheck"
    package.parent.mkdir()
    (source / "src/mccann_hub/devkit_example").rename(package)
    (source / "src/mccann_hub").rmdir()
    marker = root / "imported"
    implementation = package / "__init__.py"
    # Acceptance instrumentation only: an import is observable even if it then fails.
    implementation.write_text(
        f"from pathlib import Path as _Marker\n_Marker({str(marker)!r}).touch()\n"
        + implementation.read_text()
    )
    run("uv", "build", "--sdist", "--out-dir", str(wheels), cwd=source)
    unpacked = root / "sdist"
    with tarfile.open(next(wheels.glob("author_demo_textcheck-*.tar.gz"))) as archive:
        archive.extractall(unpacked, filter="data")
    rebuilt = next(unpacked.iterdir())
    run("uv", "build", "--wheel", "--out-dir", str(wheels), cwd=rebuilt)
    assert not marker.exists(), "Building executed plugin code"
    return rebuilt, marker


def author_tests(root, project, env, source, constraints):
    python = str(root / "venv/bin/python")
    run(
        "uv", "pip", "install", "--python", python, "--constraint", str(constraints), "pytest>=8,<9"
    )
    run(
        python,
        "-I",
        "-m",
        "pytest",
        "-q",
        "-c",
        str(source / "pyproject.toml"),
        str(source / "tests"),
        cwd=project,
        env=env,
    )
    code = """
import sys
from pathlib import Path
import mccann_hub.devkit, author_demo.textcheck
for module in (mccann_hub.devkit, author_demo.textcheck):
    assert Path(module.__file__).is_relative_to(Path(sys.prefix)), module.__file__
assert all(not Path(p).is_relative_to(Path(sys.argv[1])) for p in sys.path if p)
"""
    run(python, "-I", "-c", code, str(ROOT), cwd=project, env=env)


def parity(root, project, env, expected, arguments=None):
    code = """
import anyio, json, os, sys
from pathlib import Path
from mccann_hub.devkit.app import create_service
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
project, expected = Path(sys.argv[1]), json.loads(sys.argv[2])
arguments = json.loads(sys.argv[4])
assert create_service(project).execute("textcheck.readme", arguments)["result"] == expected
async def check():
    params = StdioServerParameters(
        command=sys.argv[3], args=["--project",str(project)], env=dict(os.environ))
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            response = await session.call_tool("textcheck.readme",arguments)
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
        json.dumps(arguments or {}),
        cwd=project,
        env=env,
    )


def typed_consumer(root, project, env):
    consumer = project / "consumer.py"
    consumer.write_text(
        "from mccann_hub.devkit.contracts import CommandResult\n"
        "def result() -> CommandResult:\n"
        "    return CommandResult('success', 'Typed consumer')\n"
    )
    arguments = (
        sys.executable,
        "-m",
        "mypy",
        "--strict",
        "--no-incremental",
        "--python-executable",
        str(root / "venv/bin/python"),
        str(consumer),
    )
    run(*arguments, cwd=project, env=env)
    consumer.write_text(consumer.read_text().replace("'success'", "'not-a-status'"))
    rejected = subprocess.run(arguments, cwd=project, env=env, capture_output=True, text=True)
    assert rejected.returncode == 1 and "[arg-type]" in rejected.stdout, rejected.stdout
    print("PASS: installed foundation types accept valid and reject invalid plugin results")


def main():
    root, wheels, constraints = map(Path, sys.argv[1:4])
    root.mkdir()
    source, marker = build(root, wheels)
    project, env = install(
        root,
        wheels,
        [
            "mccann_hub.devkit",
            "author_demo.textcheck",
            "mccann_hub.devkit_example",
            "mccann_hub.devkit_mcp",
        ],
        constraints,
    )
    absent(
        root,
        project,
        env,
        ["mccann_hub.devkit_go", "mccann_hub.devkit_odoo", "mccann_hub.devkit_beads", "odoo"],
    )
    assert not (root / "config/devkit/policy.toml").exists(), "Installation wrote policy"
    typed_consumer(root, project, env)
    (project / "README.md").write_text("# Project\nUseful verification.\n")
    # Discovery requires no trust or project activation.
    discovered = cli(root, project, env, "plugins")["result"]["data"]["plugins"]
    assert any(plugin["id"] == "textcheck" for plugin in discovered), discovered
    details = cli(root, project, env, "plugins", "list", "--details")["result"]["data"]
    row = next(item for item in details["plugins"] if item["id"] == "textcheck")
    assert row["selected"] is False and row["trust"] == "not-configured"
    assert not marker.exists(), "Metadata discovery imported the plugin"
    (project / "devkit.toml").write_text('plugins=["textcheck","example"]')
    untrusted = cli(root, project, env, "run", "textcheck.readme", expected=3)
    assert untrusted["result"]["reason"] == "UNTRUSTED_PLUGIN"
    assert not marker.exists(), "Untrusted selection imported the plugin"
    policy(root, project, ["textcheck", "example"], {})
    trust = root / "config/devkit/policy.toml"
    trust.write_text(
        trust.read_text()
        .replace("mccann-hub-", "")
        .replace("author-demo-textcheck", "devkit-textcheck")
    )
    legacy = cli(root, project, env, "run", "textcheck.readme", expected=3)
    assert legacy["result"]["reason"] == "UNTRUSTED_PLUGIN"
    assert not marker.exists(), "Legacy distribution trust authorized a renamed plugin"
    details = cli(root, project, env, "plugins", "list", "--details")["result"]["data"]
    assert next(item for item in details["plugins"] if item["id"] == "textcheck")["selected"]
    assert not marker.exists(), "Detailed inspection imported the plugin"
    policy(root, project, ["textcheck", "example"], {})
    trusted_denied = cli(root, project, env, "run", "textcheck.readme", expected=2)
    assert trusted_denied["result"]["reason"] == "DENIED"
    assert marker.exists(), "Trusted registration was not attempted"
    policy(
        root,
        project,
        ["textcheck", "example"],
        {"textcheck.readme": ["read_fs"], "example.readme": ["read_fs"]},
    )
    result = cli(root, project, env, "run", "textcheck.readme")
    assert result["result"]["data"] == {"lines": 2, "trailing_whitespace_lines": []}
    assert marker.exists()
    parity(root, project, env, result["result"])
    invalid = cli(
        root,
        project,
        env,
        "run",
        "textcheck.readme",
        "--args",
        '{"filename":"../secret"}',
        expected=3,
    )
    assert invalid["result"]["reason"] == "INVALID_INPUT"
    parity(root, project, env, invalid["result"], {"filename": "../secret"})
    author_tests(root, project, env, source, constraints)
    (project / "README.md").write_text("# Project  \nUseful verification.\n")
    failed = cli(root, project, env, "run", "textcheck.readme", expected=1)
    assert failed["result"]["data"]["trailing_whitespace_lines"] == [1]
    parity(root, project, env, failed["result"])
    (project / "README.md").unlink()
    os.mkfifo(project / "README.md")
    unsafe = cli(root, project, env, "run", "textcheck.readme", expected=2)
    assert unsafe["result"]["reason"] == "UNSAFE_PATH"
    (project / "README.md").unlink()
    policy(root, project, ["textcheck", "example"], {"example.readme": ["read_fs"]})
    denied = cli(root, project, env, "run", "textcheck.readme", expected=2)
    assert denied["result"]["reason"] == "DENIED"
    parity(root, project, env, denied["result"])
    (project / "devkit.toml").write_text('plugins=["example"]')
    (project / "README.md").write_text("Clean text.\n")
    marker.unlink(missing_ok=True)
    cli(root, project, env, "run", "example.readme")
    assert not marker.exists(), "Deactivated plugin was imported"
    run(
        "uv",
        "pip",
        "uninstall",
        "--python",
        str(root / "venv/bin/python"),
        "author-demo-textcheck",
    )
    # This environment has no other author_demo distributions; the namespace disappears too.
    absent(root, project, env, ["author_demo"])
    (project / "README.md").write_text("Clean text.\n")
    marker.unlink(missing_ok=True)
    cli(root, project, env, "run", "example.readme")
    assert not marker.exists(), "Deactivated plugin was imported"
    shown = cli(root, project, env, "runs", "show", result["run_id"])["result"]["data"]
    assert shown["run"]["result"] == result["result"]
    print(
        "PASS: renamed third-party template, wheel discovery/trust/authorization, "
        "three surfaces, removal"
    )


if __name__ == "__main__":
    main()
