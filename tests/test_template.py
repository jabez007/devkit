from pathlib import Path

from devkit.app import create_service

from tests.contract_helpers import assert_success, service_with_grants


def test_plugin_template(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "examples/plugin/src"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    from devkit_example import register

    plugin = register()
    service = service_with_grants(create_service(tmp_path).settings, plugin.commands)
    (tmp_path / "README.md").write_text("Clean text.\n")
    assert_success(service, "example.readme", {}, {"lines": 1, "trailing_whitespace_lines": []})
    assert (
        service.execute("example.readme", {"filename": "../outside"})["result"]["reason"]
        == "INVALID_INPUT"
    )
    missing = service.execute("example.readme", {"filename": "README.rst"})["result"]
    assert "README.rst" in missing["summary"]
