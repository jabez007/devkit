"""The devkit-odoo command validates addons without plugin selection or operator policy."""

import json

import pytest
from mccann_hub.devkit_odoo.cli import main

VIEWS = """<odoo>
<record id="acme_action" model="ir.actions.act_window"/>
<menuitem id="menu" action="{action}"/>
</odoo>"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A bare checkout: no devkit.toml and no operator policy."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-config"))
    root = tmp_path / "repo"
    module = root / "addons/acme"
    module.mkdir(parents=True)
    write_module(module, "acme_action")
    return root


def write_module(module, action):
    (module / "views.xml").write_text(VIEWS.format(action=action))
    (module / "__manifest__.py").write_text(
        repr({"name": "Acme", "depends": ["base"], "data": ["views.xml"]})
    )


def test_valid_addons_pass_without_configuration(project, capsys):
    assert main(["--project", str(project)]) == 0
    assert "Examined 1 modules" in capsys.readouterr().out


def test_undefined_reference_fails_with_its_location(project, capsys):
    write_module(project / "addons/acme", "acme_action_typo")
    assert main(["--project", str(project)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("failed (UNDEFINED_XML_ID)")
    assert "views.xml:3:1: XML ID acme_action_typo is not defined" in out


def test_update_mode_flag_keeps_absent_ids_unknown(project):
    write_module(project / "addons/acme", "acme_action_typo")
    assert main(["--project", str(project), "--install-mode", "update"]) == 0


def test_json_output_carries_status_reason_and_data(project, capsys):
    write_module(project / "addons/acme", "acme_action_typo")
    main(["--project", str(project), "--json"])
    result = json.loads(capsys.readouterr().out)
    assert (result["status"], result["reason"]) == ("failed", "UNDEFINED_XML_ID")
    assert result["data"]["install_mode"] == "fresh"


def test_devkit_toml_options_apply_and_flags_override_them(project):
    (project / "addons").rename(project / "custom")
    (project / "devkit.toml").write_text(
        '[options.odoo]\naddons_paths = ["custom"]\ninstall_mode = "update"\n'
    )
    write_module(project / "custom/acme", "acme_action_typo")
    assert main(["--project", str(project)]) == 0
    assert main(["--project", str(project), "--install-mode", "fresh"]) == 1


def test_missing_project_is_an_error(tmp_path, capsys):
    assert main(["--project", str(tmp_path / "missing")]) == 3
    assert "INVALID_CONFIG" in capsys.readouterr().out
