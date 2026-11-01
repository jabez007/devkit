import pytest
from mccann_hub.devkit.app import create_service


def run(project, arguments=None):
    return create_service(project).execute("odoo.module.validate", arguments)["result"]


def test_valid_manifest_reports_coverage_and_unresolved_dependencies(odoo_project):
    project, _ = odoo_project
    result = run(project)
    assert result["status"] == "success"
    assert result["data"]["modules"][0]["unresolved_dependencies"] == ["base"]
    assert "runtime" in result["data"]["not_checked"]
    assert run(project, {"strict_dependencies": True})["status"] == "blocked"
    assert {"go.test", "odoo.module.validate"} <= create_service(project).commands.keys()


@pytest.mark.parametrize(
    "manifest",
    [
        "invalid syntax",
        "{}",
        "{'name': 12}",
        "{'name':'Example', 'depends':'base'}",
        "{'name':'Example', 'version':'20.0.1.0.0'}",
        "{'name':'Example', 'data':['missing.xml']}",
        "{'name':'Example', 'data':['../escape.xml']}",
    ],
)
def test_bad_manifests(odoo_project, manifest):
    project, module = odoo_project
    (module / "__manifest__.py").write_text(manifest)
    assert run(project)["status"] == "failed"


def test_manifest_expressions_never_execute(odoo_project):
    project, module = odoo_project
    marker = project / "executed"
    (module / "__manifest__.py").write_text(
        "{'name': __import__('pathlib').Path(" + repr(str(marker)) + ").write_text('bad')}"
    )
    assert run(project)["status"] == "failed"
    assert not marker.exists()


def test_symlinks_and_duplicate_modules(odoo_project, tmp_path):
    project, module = odoo_project
    outside = tmp_path / "outside.xml"
    outside.write_text("outside")
    (module / "data.xml").symlink_to(outside)
    (module / "__manifest__.py").write_text("{'name':'Example', 'data':['data.xml']}")
    assert run(project)["status"] == "failed"
    duplicate = project / "other/example"
    duplicate.mkdir(parents=True)
    (duplicate / "__manifest__.py").write_text("{'name':'Example'}")
    assert run(project, {"addons_paths": ["addons", "other"]})["reason"] == "INVALID_ADDONS"
    assert run(project, {"addons_paths": ["../"]})["reason"] == "INVALID_ADDONS"


def test_bounded_manifest(odoo_project):
    project, module = odoo_project
    (module / "__manifest__.py").write_text(" " * 262145)
    assert run(project)["status"] == "failed"
