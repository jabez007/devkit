"""Shared temporary project fixtures with isolated operator policy."""

import json

import pytest


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


@pytest.fixture
def odoo_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    module = project / "addons/example"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(repr({"name": "Example", "depends": ["base"]}))
    (project / "devkit.toml").write_text('plugins=["odoo", "go"]')
    config = tmp_path / "config/devkit"
    config.mkdir(parents=True)
    policy = config / "policy.toml"
    policy.write_text(
        '[trusted_plugins]\ndevkit-odoo="0.5.0"\ndevkit-go="0.1.0"\n'
        '[commands."odoo.module.validate"]\nproject='
        + json.dumps(str(project))
        + '\neffects=["read_fs"]\nsurfaces=["python","cli","mcp"]'
    )
    policy.chmod(0o600)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return project, module
