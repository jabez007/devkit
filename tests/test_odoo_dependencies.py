import json

import pytest
from mccann_hub.devkit.app import create_service


def validate(project, **arguments):
    envelope = create_service(project).execute("odoo.module.validate", arguments)
    return envelope["result"]


def manifest(module, **fields):
    (module / "__manifest__.py").write_text(repr({"name": "Example", **fields}))


def statuses(result):
    return {edge["name"]: edge["status"] for edge in result["data"]["modules"][0]["dependencies"]}


def test_custom_addon_has_unknown_not_missing_dependencies(odoo_project):
    project, module = odoo_project
    manifest(module, depends=["base", "sale"])
    result = validate(project)
    assert result["status"] == "success"
    assert statuses(result) == {"base": "unknown", "sale": "unknown"}
    assert result["data"]["inventory"]["complete"] is False
    assert result["data"]["inventory"]["scan_complete"] is True
    strict = validate(project, strict_dependencies=True)
    assert strict["status"] == "blocked"
    assert strict["reason"] == "INCOMPLETE_INVENTORY"


@pytest.mark.parametrize("strict", [False, True])
def test_confirmed_missing_fails_only_after_explicit_completeness(odoo_project, strict):
    project, _ = odoo_project
    result = validate(project, strict_dependencies=strict, inventory={"complete": True})
    assert result["status"] == "failed"
    assert result["reason"] == "MISSING_DEPENDENCIES"
    assert statuses(result) == {"base": "missing"}


def test_completeness_can_cover_only_a_custom_namespace(odoo_project):
    project, module = odoo_project
    manifest(module, depends=["base", "acme_absent", "other_addon"])
    result = validate(project, inventory={"complete_prefixes": ["acme_"]})
    assert statuses(result) == {
        "base": "unknown",
        "acme_absent": "missing",
        "other_addon": "unknown",
    }
    assert result["status"] == "failed"
    assert result["data"]["inventory"]["complete"] is False


def test_multiple_paths_resolve_internal_and_external_modules(odoo_project):
    project, module = odoo_project
    manifest(module, depends=["acme_core", "base", "base_tier_validation"])
    for relative in ("addons/acme_core", "vendor/odoo/base", "vendor/oca/base_tier_validation"):
        addon = project / relative
        addon.mkdir(parents=True)
        manifest(addon)
    result = validate(
        project,
        module="example",
        strict_dependencies=True,
        addons_paths=["addons", "vendor/odoo", "vendor/oca"],
    )
    assert result["status"] == "success"
    assert set(statuses(result).values()) == {"resolved"}
    assert result["data"]["inventory"]["module_count"] == 4
    edges = result["data"]["modules"][0]["dependencies"]
    assert (
        next(edge for edge in edges if edge["name"] == "base_tier_validation")["path"]
        == "vendor/oca/base_tier_validation"
    )


@pytest.mark.parametrize(
    "depends", ["base", ["../escape"], ["sale.order"], [None], [""], ["base\n"], None]
)
def test_malformed_dependency_declarations_are_invalid(odoo_project, depends):
    project, module = odoo_project
    manifest(module, depends=depends)
    result = validate(project)
    assert result["status"] == "failed"
    assert result["reason"] == "INVALID_DEPENDENCIES"
    assert any(edge["status"] == "invalid" for edge in result["data"]["modules"][0]["dependencies"])
    assert "depends" in json.dumps(result["data"]["modules"][0]["errors"])


def test_external_requirements_are_reported_without_importing_or_resolving(odoo_project):
    project, module = odoo_project
    manifest(
        module,
        depends=["base"],
        auto_install=["base"],
        external_dependencies={"python": ["unavailable-library>=2"], "bin": ["nonexistent-tool"]},
    )
    base = project / "addons/base"
    base.mkdir()
    manifest(base)
    result = validate(
        project, strict_dependencies=True, module="example", inventory={"complete": True}
    )
    assert result["status"] == "success"
    requirements = result["data"]["modules"][0]["external_dependencies"]
    assert {item["kind"] for item in requirements} == {"python", "bin"}
    assert all(item["status"] == "unknown" for item in requirements)
    assert "external dependencies" in result["data"]["not_checked"]


def test_implicit_base_and_auto_install_use_the_same_dependencies(odoo_project):
    project, module = odoo_project
    manifest(module, auto_install=["base"])
    result = validate(project)
    assert result["status"] == "success"
    assert result["data"]["modules"][0]["dependencies"][0]["implicit"] is True


def test_incomplete_scan_cannot_establish_missing_dependencies(odoo_project):
    project, _ = odoo_project
    result = validate(project, addons_paths=["addons", "missing"], inventory={"complete": True})
    assert result["status"] == "blocked"
    assert result["reason"] == "MISSING_ADDONS"
    assert result["data"]["inventory"]["scan_complete"] is False


def test_invalid_module_directory_is_not_a_resolved_dependency(odoo_project):
    project, _ = odoo_project
    addon = project / "addons/bad-name"
    addon.mkdir()
    manifest(addon)
    result = validate(project)
    assert result["status"] == "failed"
    assert "bad-name" in result["summary"]
