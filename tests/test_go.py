import json

import pytest
from devkit.app import create_service


@pytest.fixture(scope="session")
def go_cache(tmp_path_factory):
    return tmp_path_factory.mktemp("go-cache")


@pytest.fixture
def go_project(tmp_path, monkeypatch, go_cache):
    project = tmp_path / "project"
    project.mkdir()
    (project / "go.mod").write_text("module example.test/check\n\ngo 1.22\n")
    (project / "main.go").write_text("package check\n")
    (project / "devkit.toml").write_text('plugins=["go"]\ntimeout=90\n')
    config = tmp_path / "config/devkit"
    config.mkdir(parents=True)
    policy = config / "policy.toml"
    policy.write_text(
        '[trusted_plugins]\ndevkit-go="0.1.0"\n[commands."go.test"]\nproject='
        + json.dumps(str(project))
        + '\neffects=["read_fs","write_fs",'
        '"execute_process","network_read","network_write"]\nsurfaces=["python"]'
    )
    policy.chmod(0o600)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("GOPROXY", "off")
    monkeypatch.setenv("GOCACHE", str(go_cache))
    return project


@pytest.mark.parametrize(
    "body,status",
    [('t.Log("ok")', "success"), ('t.Fatal("failed")', "failed"), ('t.Skip("skipped")', "blocked")],
)
def test_real_go_tests(go_project, body, status):
    (go_project / "main_test.go").write_text(
        f'package check\nimport "testing"\nfunc TestExample(t *testing.T) {{ {body} }}\n'
    )
    result = create_service(go_project).execute("go.test")
    assert result["result"]["status"] == status, result
    assert result["producer"]["distribution"] == "devkit-go"
    assert result["result"]["data"]["tool_version"].startswith("go version")


def test_no_tests_and_missing_go(go_project, monkeypatch):
    assert create_service(go_project).execute("go.test")["result"]["reason"] == "NO_TESTS"
    monkeypatch.setenv("PATH", "/missing")
    assert create_service(go_project).execute("go.test")["result"]["reason"] == "MISSING_TOOL"
