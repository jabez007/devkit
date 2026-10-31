"""Build and exercise independent installed distributions outside the workspace."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def install(root, wheels, names, constraints):
    run("uv", "venv", "--python", sys.executable, str(root / "venv"))
    selected = [str(next(wheels.glob(f"{name}-*.whl"))) for name in names]
    run(
        "uv",
        "pip",
        "install",
        "--python",
        str(root / "venv/bin/python"),
        "--constraint",
        str(constraints),
        *selected,
    )
    project = root / "project"
    project.mkdir()
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_STATE_HOME": str(root / "state"),
        "GOPROXY": "off",
        "GOCACHE": str(root.parent / "go-cache"),
    }
    env.pop("PYTHONPATH", None)
    return project, env


def cli(root, project, env, *args, expected=0):
    result = subprocess.run(
        [str(root / "venv/bin/devkit"), "--project", str(project), "--json", *args],
        env=env,
        cwd=project,
        text=True,
        capture_output=True,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    return json.loads(result.stdout)


def policy(root, project, names, commands):
    path = root / "config/devkit/policy.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "[trusted_plugins]\n" + "".join(f'devkit-{name}="0.1.0"\n' for name in names)
    for command, effects in commands.items():
        text += f'\n[commands."{command}"]\nproject={json.dumps(str(project))}\n'
        text += f'effects={json.dumps(effects)}\nsurfaces=["cli","python","mcp"]\n'
    path.write_text(text)
    path.chmod(0o600)


def absent(root, project, env, names):
    code = (
        f"import importlib.util; assert all(importlib.util.find_spec(n) is None for n in {names!r})"
    )
    run(str(root / "venv/bin/python"), "-c", code, cwd=project, env=env)


def exercise_foundation(root, wheels, constraints):
    project, env = install(root, wheels, ["devkit"], constraints)
    absent(root, project, env, ["devkit_go", "devkit_odoo", "mcp", "docker", "odoo"])
    assert cli(root, project, env, "doctor")["result"]["status"] == "success"
    assert not cli(root, project, env, "plugins")["result"]["data"]["plugins"]
    print("PASS: foundation only")


def exercise_go(root, wheels, constraints):
    project, env = install(root, wheels, ["devkit", "devkit_go"], constraints)
    absent(root, project, env, ["devkit_odoo", "mcp", "odoo"])
    (project / "devkit.toml").write_text('plugins=["go"]\ntimeout=90\n')
    (project / "go.mod").write_text("module example.test/wheel\ngo 1.22\n")
    test = project / "sample_test.go"
    test.write_text('package sample\nimport "testing"\nfunc TestWorks(t *testing.T) {}\n')
    effects = ["read_fs", "write_fs", "execute_process", "network_read", "network_write"]
    policy(root, project, ["go"], {"go.test": effects})
    assert cli(root, project, env, "run", "go.test")["result"]["data"]["tests"]["passed"] == 1
    test.write_text(
        'package sample\nimport "testing"\nfunc TestFails(t *testing.T) { t.Fatal("fail") }'
    )
    assert (
        cli(root, project, env, "run", "go.test", expected=1)["result"]["reason"] == "TEST_FAILED"
    )
    print("PASS: Go only, real passing and failing tests")


def exercise_odoo(root, wheels, constraints):
    project, env = install(root, wheels, ["devkit", "devkit_odoo"], constraints)
    absent(root, project, env, ["devkit_go", "mcp", "odoo", "docker"])
    (project / "devkit.toml").write_text('plugins=["odoo"]\n[profiles]\nstatic=["odoo.manifests"]')
    module = project / "addons/example"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text("{'name':'Example'}")
    policy(root, project, ["odoo"], {"odoo.module.validate": ["read_fs"]})
    assert cli(root, project, env, "check", "static")["result"]["status"] == "success"
    print("PASS: offline Odoo only and profile execution")


def exercise_template(root, wheels, constraints):
    project, env = install(root, wheels, ["devkit", "devkit_example"], constraints)
    (project / "devkit.toml").write_text('plugins=["example"]')
    policy(root, project, ["example"], {"example.greet": []})
    result = cli(root, project, env, "run", "example.greet", "--args", '{"name":"Dev"}')
    assert result["result"]["data"] == {"greeting": "Hello, Dev"}
    print("PASS: independently built plugin template")


def exercise_artifact_pin(root, wheels, constraints):
    project, env = install(root, wheels, ["devkit", "devkit_sample"], constraints)
    (project / "devkit.toml").write_text('plugins=["sample"]')
    marker = root / "imported"
    env["DEVKIT_TEST_IMPORT_MARKER"] = str(marker)
    policy(root, project, [], {"sample.inspect": []})
    wheel = next(wheels.glob("devkit_sample-*.whl"))
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with (root / "config/devkit/policy.toml").open("a") as stream:
        stream.write('\n[trusted_plugins.devkit-sample]\nversion="0.1.0"\n')
        stream.write(f'wheel={json.dumps(str(wheel))}\nsha256="{digest}"\n')
    result = cli(root, project, env, "run", "sample.inspect")
    assert result["producer"]["artifact_sha256"] == digest
    assert marker.exists()
    marker.unlink()
    source = next((root / "venv/lib").glob("python*/site-packages/devkit_sample/__init__.py"))
    source.unlink()  # Do not modify a file that could be hard-linked into an installer cache.
    source.write_text('raise RuntimeError("replaced distribution with the same version")')
    result = cli(root, project, env, "run", "sample.inspect", expected=3)
    assert result["result"]["reason"] == "ARTIFACT_MISMATCH"
    assert not marker.exists()
    print("PASS: pinned installed wheel rejects same-version replacement before import")


def exercise_mcp(root, wheels, constraints):
    project, env = install(
        root,
        wheels,
        ["devkit", "devkit_go", "devkit_odoo", "devkit_mcp", "devkit_sample"],
        constraints,
    )
    absent(root, project, env, ["odoo", "docker"])
    marker = root / "imported"
    env["DEVKIT_TEST_IMPORT_MARKER"] = str(marker)
    cli(root, project, env, "plugins")
    assert not marker.exists()
    (project / "devkit.toml").write_text('plugins=["sample","go","odoo"]')
    cli(root, project, env, "run", "sample.inspect", expected=3)
    assert not marker.exists()
    policy(root, project, ["sample", "go", "odoo"], {"sample.inspect": [], "sample.invalid": []})
    code = """
import anyio, os, sys
from datetime import timedelta
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def check():
    params = StdioServerParameters(
        command=sys.argv[1], args=["--project",sys.argv[2]], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=10)
        ) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == {"sample.inspect", "sample.invalid"}
            good = await session.call_tool("sample.inspect", {})
            assert good.structuredContent["result"]["data"]["value"] == 42
            bad = await session.call_tool("sample.invalid", {})
            assert bad.isError
            assert bad.structuredContent["result"]["reason"] == "INVALID_OUTPUT"
anyio.run(check)
"""
    run(
        str(root / "venv/bin/python"),
        "-c",
        code,
        str(root / "venv/bin/devkit-mcp"),
        str(project),
        env=env,
        cwd=project,
    )
    print("PASS: installed MCP, plugin composition, disabled imports, invalid output")


def main():
    with tempfile.TemporaryDirectory(prefix="devkit-wheels-") as temporary:
        root = Path(temporary)
        wheels = root / "wheels"
        run("uv", "build", "--all-packages", "--out-dir", str(wheels), cwd=ROOT)
        run("uv", "build", "tests/fixtures/plugin", "--out-dir", str(wheels), cwd=ROOT)
        run("uv", "build", "examples/plugin", "--out-dir", str(wheels), cwd=ROOT)
        lock = tomllib.loads((ROOT / "uv.lock").read_text())
        constraints = root / "constraints.txt"
        constraints.write_text(
            "\n".join(
                f"{p['name']}=={p['version']}" for p in lock["package"] if "registry" in p["source"]
            )
        )
        for exercise in (
            exercise_foundation,
            exercise_go,
            exercise_odoo,
            exercise_template,
            exercise_artifact_pin,
            exercise_mcp,
        ):
            target = root / exercise.__name__
            target.mkdir()
            exercise(target, wheels, constraints)


if __name__ == "__main__":
    main()
