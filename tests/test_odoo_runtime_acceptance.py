"""Installed Devkit commands against pinned Odoo 19 and PostgreSQL containers."""

import json
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from mccann_hub.devkit.contracts import EFFECTS

from tests.test_odoo_runtime_reporting import (
    ODOO_IMAGE,
    SOURCES,
    docker,
)

pytest_plugins = ["tests.test_odoo_runtime_reporting"]

pytestmark = [
    pytest.mark.odoo_runtime,
    pytest.mark.skipif(
        os.environ.get("DEVKIT_ODOO_RUNTIME") != "1",
        reason="Set DEVKIT_ODOO_RUNTIME=1 for container acceptance",
    ),
]
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def installed_runtime_image(tmp_path_factory):
    context = tmp_path_factory.mktemp("odoo-installed-runtime")
    wheels = context / "wheels"
    for package in ("mccann-hub-devkit", "mccann-hub-devkit-odoo"):
        subprocess.run(
            ["uv", "build", "--offline", "--package", package, "--wheel", "--out-dir", str(wheels)],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    with (context / "requirements.txt").open("w") as stream:
        subprocess.run(
            [
                "uv",
                "export",
                "--locked",
                "--offline",
                "--no-dev",
                "--package",
                "mccann-hub-devkit-odoo",
                "--no-emit-workspace",
                "--format",
                "requirements-txt",
            ],
            cwd=ROOT,
            check=True,
            stdout=stream,
        )
    (context / "Dockerfile").write_text(
        f"FROM {ODOO_IMAGE}\nUSER root\nCOPY requirements.txt /tmp/requirements.txt\n"
        "RUN python3 -m venv --system-site-packages --without-pip /opt/devkit && "
        "/opt/devkit/bin/python -m pip install --require-hashes -r /tmp/requirements.txt\n"
        "COPY wheels /tmp/wheels\n"
        "RUN /opt/devkit/bin/python -m pip install --no-deps /tmp/wheels/*.whl\n"
        'USER odoo\nENTRYPOINT ["/opt/devkit/bin/devkit"]\n'
    )
    image = "devkit-odoo-acceptance:" + uuid.uuid4().hex[:12]
    try:
        try:
            docker("build", "--tag", image, str(context), timeout=180)
        except subprocess.CalledProcessError as exc:
            (context / "build.log").write_text(exc.stdout + exc.stderr)
            pytest.fail(exc.stderr[-6000:])
        yield image
    finally:
        subprocess.run(["docker", "image", "rm", image], capture_output=True)


def prepare_project(project, kind):
    tests = project / "addons/sample/tests"
    tests.mkdir(parents=True)
    (tests.parent / "__manifest__.py").write_text(
        repr(
            {
                "name": "Sample",
                "version": "19.0.1.0.0",
                "depends": ["base", "web"],
                "license": "GPL-3",
            }
        )
    )
    (tests.parent / "__init__.py").write_text("")
    source = SOURCES.get(kind, "")
    if kind == "http":
        source = """@tagged('-at_install', 'post_install')
class BrowserProbe(HttpCase):
    def test_login(self):
        self.assertEqual(self.url_open('/web/login').status_code, 200)
"""
    (tests / "__init__.py").write_text("from . import test_sample\n" if source else "")
    (tests / "test_sample.py").write_text(
        "from unittest import skip, SkipTest\n"
        "from odoo.tests.common import TransactionCase, HttpCase, tagged\n" + source
    )
    (project / "devkit.toml").write_text(
        'plugins=["odoo"]\ntimeout=150\n[options.odoo]\nmodule="sample"\n'
    )
    policy = project.parent / (project.name + "-operator") / "devkit/policy.toml"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        '[trusted_plugins]\nmccann-hub-devkit-odoo="0.6.0"\n'
        '[commands."odoo.module.test"]\nproject="/project"\n'
        f'effects={json.dumps(sorted(EFFECTS))}\nsurfaces=["cli"]\n'
    )
    policy.chmod(0o600)


def run_command(project, network, image):
    name = "devkit-odoo-command-" + uuid.uuid4().hex[:12]
    operator = project.parent / (project.name + "-operator")
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--network",
                network,
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--env",
                "HOME=/tmp/odoo",
                "--env",
                "USER=devkit",
                "--env",
                "LOGNAME=devkit",
                "--env",
                "PGHOST=postgres",
                "--env",
                "PGUSER=odoo",
                "--env",
                "PGPORT=5432",
                "--env",
                "XDG_CONFIG_HOME=/operator",
                "--env",
                "XDG_STATE_HOME=/project/state",
                "--mount",
                f"type=bind,src={project},dst=/project",
                "--mount",
                f"type=bind,src={operator},dst=/operator,readonly",
                image,
                "--project",
                "/project",
                "--json",
                "run",
                "odoo.module.test",
            ],
            text=True,
            capture_output=True,
            timeout=180,
        )
        (project / "command.stdout").write_text(result.stdout)
        (project / "command.stderr").write_text(result.stderr)
        assert result.stdout.strip(), result.stderr
        return json.loads(result.stdout)["result"]
    finally:
        subprocess.run(["docker", "rm", "--force", "--volumes", name], capture_output=True)


def assert_database_removed(postgres, result):
    assert result["data"]["cleanup"]["status"] == "complete", result
    database = result["data"]["database"]
    assert database.startswith("devkit_test_")
    found = docker(
        "exec",
        postgres,
        "psql",
        "-U",
        "odoo",
        "-d",
        "postgres",
        "-Atc",
        "SELECT datname FROM pg_database",
    ).stdout.splitlines()
    assert database not in found


@pytest.mark.parametrize(
    "kind,status,reason,run",
    [
        ("pass", "success", None, 1),
        ("fail", "failed", "TEST_FAILED", 1),
        ("none", "blocked", "NO_TESTS", 0),
        ("skip", "blocked", "NO_TESTS", 0),
        ("http", "success", None, 1),
    ],
)
def test_installed_runtime_command(
    tmp_path, runtime_server, installed_runtime_image, kind, status, reason, run
):
    project = tmp_path / "project"
    prepare_project(project, kind)
    network, postgres = runtime_server
    result = run_command(project, network, installed_runtime_image)
    assert (result["status"], result["reason"]) == (status, reason), result
    assert result["data"]["tests"]["run"] == run
    if kind == "fail":
        assert result["data"]["failures"][0]["test"].endswith("Probe.test_fixture")
        assert "1 != 2" in result["data"]["failures"][0]["output"]
    assert_database_removed(postgres, result)


def test_installed_concurrent_jobs_have_distinct_owned_databases(
    tmp_path, runtime_server, installed_runtime_image
):
    projects = [tmp_path / "one", tmp_path / "two"]
    for project in projects:
        prepare_project(project, "pass")
    network, postgres = runtime_server
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda project: run_command(project, network, installed_runtime_image),
                projects,
            )
        )
    assert len({result["data"]["database"] for result in results}) == 2
    for result in results:
        assert result["status"] == "success", result
        assert_database_removed(postgres, result)
