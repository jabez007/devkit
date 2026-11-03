"""Native Odoo runner acceptance; opt in explicitly before starting containers."""

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from mccann_hub import devkit_odoo

ODOO_IMAGE = "odoo@sha256:dd9013e669caaa23d26765dc55814655eaeecca7cfc2c265dbabae913bce22fd"
POSTGRES_IMAGE = "postgres@sha256:3b0cda93be7c8dba2ed484d19393d93845dc3dafb88973e248ba8e6d99d784e1"
ADDONS = Path(devkit_odoo.__file__).parent / "_runtime_addons"
pytestmark = [
    pytest.mark.odoo_runtime,
    pytest.mark.skipif(
        os.environ.get("DEVKIT_ODOO_RUNTIME") != "1",
        reason="Set DEVKIT_ODOO_RUNTIME=1 for container acceptance",
    ),
]


def docker(*arguments, **kwargs):
    return subprocess.run(
        ["docker", *arguments], text=True, capture_output=True, check=True, **kwargs
    )


@pytest.fixture(scope="module")
def runtime_server():
    network = "devkit-odoo-runtime-" + uuid.uuid4().hex[:12]
    database = network + "-db"
    docker("network", "create", "--label", "devkit.acceptance=odoo-runtime", network)
    try:
        docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            database,
            "--network",
            network,
            "--network-alias",
            "postgres",
            "--label",
            "devkit.acceptance=odoo-runtime",
            "--env",
            "POSTGRES_USER=odoo",
            "--env",
            "POSTGRES_DB=postgres",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            POSTGRES_IMAGE,
        )
        for _ in range(30):
            ready = subprocess.run(
                ["docker", "exec", database, "pg_isready", "-U", "odoo", "-d", "postgres"],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.fail("The disposable PostgreSQL server did not become ready")
        yield network, database
    finally:
        subprocess.run(["docker", "rm", "--force", "--volumes", database], capture_output=True)
        docker("network", "rm", network)


def run_native(project, network, database, token):
    name = "devkit-odoo-case-" + token[:12]
    arguments = [
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
        "ODOO_TEST_FAILURE_RETRIES=0",
        "--env",
        "DEVKIT_ODOO_REPORT=/project/report.json",
        "--env",
        f"DEVKIT_ODOO_JOB_TOKEN={token}",
        "--mount",
        f"type=bind,src={project},dst=/project",
        "--mount",
        f"type=bind,src={ADDONS},dst=/reporting,readonly",
        "--entrypoint",
        "/usr/bin/odoo",
        ODOO_IMAGE,
        "--config=/dev/null",
        "--db_host=postgres",
        "--db_port=5432",
        "--db_user=odoo",
        f"--database={database}",
        "--init=sample",
        "--addons-path=/reporting,/project/addons",
        "--load=base,web,devkit_test_reporter",
        "--data-dir=/project/data",
        "--stop-after-init",
        "--no-http",
        "--max-cron-threads=0",
        "--workers=0",
        "--test-enable",
        "--test-tags=/sample",
    ]
    try:
        result = subprocess.run(arguments, text=True, capture_output=True, timeout=180)
        (project / "odoo.log").write_text(result.stdout + result.stderr)
        return result
    finally:
        subprocess.run(["docker", "rm", "--force", "--volumes", name], capture_output=True)


SOURCES = {
    "pass": """class Probe(TransactionCase):
    def test_fixture(self):
        self.assertEqual(2-1, 1)
""",
    "fail": """class Probe(TransactionCase):
    def test_fixture(self):
        self.assertEqual(1, 2)
""",
    "none": "",
    "skip": """class Probe(TransactionCase):
    @skip('synthetic')
    def test_fixture(self):
        self.fail('must remain skipped')
""",
    "skip_duplicate": """class Probe(TransactionCase):
    @skip('synthetic')
    def test_fixture(self):
        self.fail('must remain skipped')
""",
    "class_skip": """class Skipped(TransactionCase):
    @classmethod
    def setUpClass(cls):
        raise SkipTest('synthetic')
    def test_skipped(self):
        self.fail('must remain skipped')

class Executed(TransactionCase):
    def test_fixture(self):
        self.assertTrue(True)
""",
    "halt": """class Probe(TransactionCase):
    def test_a_halt(self):
        self._outcome.result.shouldStop = True
    def test_z_unexecuted(self):
        self.fail('must remain unexecuted')
""",
}


@pytest.mark.parametrize(
    "kind,exit_code,collected,run,failed,skipped,complete",
    [
        ("pass", 0, 1, 1, 0, 0, True),
        ("fail", 1, 1, 1, 1, 0, True),
        ("none", 0, 0, 0, 0, 0, True),
        ("skip", 0, 1, 0, 0, 1, True),
        ("skip_duplicate", 0, 2, 0, 0, 2, True),
        ("class_skip", 0, 2, 1, 0, 1, True),
        ("halt", 0, 2, 1, 0, 0, False),
    ],
)
def test_native_report_matches_actual_odoo_outcomes(
    tmp_path, runtime_server, kind, exit_code, collected, run, failed, skipped, complete
):
    project = tmp_path / "project"
    tests = project / "addons/sample/tests"
    tests.mkdir(parents=True)
    (tests.parent / "__manifest__.py").write_text(
        repr({"name": "Sample", "version": "19.0.1.0.0", "depends": ["base"], "license": "GPL-3"})
    )
    (tests.parent / "__init__.py").write_text("")
    initializer = "from . import test_sample\n" if SOURCES[kind] else ""
    if kind == "skip_duplicate":
        initializer += "from . import test_sample as test_alias\n"
    (tests / "__init__.py").write_text(initializer)
    (tests / "test_sample.py").write_text(
        "from unittest import skip, SkipTest\nfrom odoo.tests.common import TransactionCase\n"
        + SOURCES[kind]
    )
    network, postgres = runtime_server
    token = uuid.uuid4().hex
    database = "devkit_report_" + token
    try:
        result = run_native(project, network, database, token)
        assert result.returncode == exit_code, result.stdout[-4000:] + result.stderr[-4000:]
        report = json.loads((project / "report.json").read_text())
        assert report["protocol"] == 1 and report["job_token"] == token
        assert report["complete"] is complete
        assert report["tests"] == {
            "collected": collected,
            "run": run,
            "failed": failed,
            "skipped": skipped,
        }
        assert len(report["failures"]) == failed
        if failed:
            assert report["failures"][0]["test"].endswith("Probe.test_fixture")
            assert "1 != 2" in report["failures"][0]["output"]
        assert (project / "report.json").stat().st_mode & 0o777 == 0o600
    finally:
        docker("exec", postgres, "dropdb", "-U", "odoo", "--if-exists", "--force", database)
