from dataclasses import replace
from threading import Event

from devkit.app import create_service


def test_non_module_entries_are_bounded_before_claiming_completeness(odoo_project):
    project, _ = odoo_project
    for number in range(10000):
        (project / "addons" / f"file_{number}").touch()
    result = create_service(project).execute(
        "odoo.module.validate", {"inventory": {"complete": True}}
    )["result"]
    assert result["status"] == "error"
    assert result["reason"] == "INVENTORY_LIMIT"
    assert result["data"]["inventory"]["scan_complete"] is False
    assert result["data"]["dependency_counts"]["missing"] == 0


def test_exact_module_limit_allows_unrelated_files(odoo_project):
    project, _ = odoo_project
    for number in range(999):
        module = project / "addons" / f"addon_{number}"
        module.mkdir()
        (module / "__manifest__.py").write_text("{'name':'Addon'}")
    (project / "addons/zzz_README.md").write_text("Not an addon")
    service = create_service(project)
    result = service.execute("odoo.module.validate", {"module": "example"})["result"]
    assert result["status"] == "success"
    assert result["data"]["inventory"]["module_count"] == 1000
    extra = project / "addons/one_more"
    extra.mkdir()
    (extra / "__manifest__.py").write_text("{'name':'Extra'}")
    result = service.execute("odoo.module.validate", {"module": "example"})["result"]
    assert result["reason"] == "INVENTORY_LIMIT"


def test_cancellation_and_deadline_prevent_false_verification(odoo_project):
    project, _ = odoo_project
    service = create_service(project)
    cancelled = Event()
    cancelled.set()
    assert (
        service.execute("odoo.module.validate", cancellation=cancelled)["result"]["status"]
        == "cancelled"
    )
    service.settings = replace(service.settings, timeout=0.000001)
    assert service.execute("odoo.module.validate")["result"]["reason"] == "TIMEOUT"


def test_symlink_loop_is_an_inventory_failure(odoo_project):
    project, _ = odoo_project
    (project / "addons/loop").symlink_to("loop", target_is_directory=True)
    result = create_service(project).execute("odoo.module.validate")["result"]
    assert result["reason"] == "INVALID_ADDONS"
    assert result["data"]["inventory"]["scan_complete"] is False
