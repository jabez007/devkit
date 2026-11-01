"""Cycle evidence through the public command and persisted result contract."""

import json
from graphlib import TopologicalSorter
from pathlib import Path
from threading import Event

import pytest
from mccann_hub.devkit.app import create_service


def addon(project, name, depends, **fields):
    module = project / "addons" / name
    module.mkdir(exist_ok=True)
    (module / "__manifest__.py").write_text(repr({"name": name, "depends": depends, **fields}))
    return module


def validate(project, **arguments):
    envelope = create_service(project).execute("odoo.module.validate", arguments)
    saved = json.loads(Path(envelope["evidence_path"]).read_text())
    assert saved["result"] == envelope["result"]
    return envelope["result"]


@pytest.mark.parametrize("strict", [False, True])
def test_confirmed_cycle_fails_even_with_unknown_dependencies(odoo_project, strict):
    project, _ = odoo_project
    addon(project, "example", ["second", "base"])
    addon(project, "second", ["third"])
    addon(project, "third", ["example"])
    result = validate(project, strict_dependencies=strict)
    assert (result["status"], result["reason"]) == ("failed", "DEPENDENCY_CYCLE")
    graph = result["data"]["dependency_graph"]
    assert graph["status"] == "cycle"
    cycle = graph["cycle"]
    assert cycle[0] == cycle[-1]
    assert set(zip(cycle, cycle[1:], strict=False)) == {
        ("example", "second"),
        ("second", "third"),
        ("third", "example"),
    }
    assert graph["edge_count"] == 3
    assert graph["excluded_edge_counts"]["unknown"] == 1
    assert not result["data"]["inventory"]["complete"]
    assert " -> ".join(cycle) in result["summary"]
    assert "__manifest__.py" in result["summary"]


def test_self_dependency_is_a_cycle(odoo_project):
    project, _ = odoo_project
    addon(project, "example", ["example"])
    result = validate(project)
    assert result["reason"] == "DEPENDENCY_CYCLE"
    assert result["data"]["dependency_graph"]["cycle"] == ["example", "example"]


def test_shared_dependencies_and_duplicate_edges_do_not_form_a_cycle(odoo_project):
    project, _ = odoo_project
    addon(project, "example", ["left", "right", "left"])
    addon(project, "left", ["base"])
    addon(project, "right", ["base"])
    addon(project, "base", [])
    result = validate(project, strict_dependencies=True)
    assert result["status"] == "success"
    graph = result["data"]["dependency_graph"]
    assert graph["status"] == "no_cycle_observed"
    assert graph["cycle"] == []
    assert graph["node_count"] == 4
    assert graph["edge_count"] == 4
    assert graph["uninspected_modules"] == []
    assert not any(graph["excluded_edge_counts"].values())
    assert result["data"]["dependency_counts"]["resolved"] == 5


def test_one_witness_from_disconnected_cycles_is_an_actual_cycle(odoo_project):
    project, _ = odoo_project
    addon(project, "example", ["example"])
    addon(project, "other", ["other"])
    first = validate(project)["data"]["dependency_graph"]
    second = validate(project)["data"]["dependency_graph"]
    assert first == second
    assert first["cycle"] in (["example", "example"], ["other", "other"])


def test_selection_does_not_read_dependency_manifests_or_claim_global_acyclicity(odoo_project):
    project, _ = odoo_project
    addon(project, "example", ["other"])
    other = addon(project, "other", ["example"])
    (other / "__manifest__.py").write_text("raise RuntimeError('must not be read')")
    result = validate(
        project, module="example", strict_dependencies=True, inventory={"complete": True}
    )
    assert result["status"] == "success"
    graph = result["data"]["dependency_graph"]
    assert graph["scope"] == "inspected_manifests"
    assert graph["status"] == "no_cycle_observed"
    assert graph["node_count"] == 1
    assert graph["edge_count"] == 0
    assert graph["uninspected_modules"] == ["other"]
    assert graph["excluded_edge_counts"]["uninspected_target"] == 1
    assert "1 inventory modules uninspected" in result["summary"]


def test_invalid_manifest_is_not_an_inspected_graph_node(odoo_project):
    project, _ = odoo_project
    addon(project, "example", ["other"])
    other = addon(project, "other", ["example"])
    (other / "__manifest__.py").write_text("{}")
    result = validate(project)
    assert result["reason"] == "INVALID_MANIFEST"
    assert result["data"]["dependency_graph"]["uninspected_modules"] == ["other"]
    assert result["data"]["dependency_graph"]["excluded_edge_counts"]["uninspected_target"] == 1
    assert not result["data"]["modules"][1]["dependencies_inspected"]


def test_invalid_declarations_never_create_edges_but_preserve_other_cycle_evidence(odoo_project):
    project, _ = odoo_project
    addon(project, "example", ["example", "../example", None])
    result = validate(project)
    assert result["reason"] == "INVALID_DEPENDENCIES"
    graph = result["data"]["dependency_graph"]
    assert graph["cycle"] == ["example", "example"]
    assert graph["edge_count"] == 1
    assert graph["excluded_edge_counts"]["invalid"] == 2


@pytest.mark.parametrize("complete", [False, True])
def test_inventory_claims_do_not_invent_graph_edges(odoo_project, complete):
    project, _ = odoo_project
    result = validate(project, strict_dependencies=True, inventory={"complete": complete})
    assert result["reason"] == ("MISSING_DEPENDENCIES" if complete else "INCOMPLETE_INVENTORY")
    graph = result["data"]["dependency_graph"]
    assert graph["status"] == "no_cycle_observed"
    assert graph["edge_count"] == 0
    assert graph["excluded_edge_counts"]["missing" if complete else "unknown"] == 1


def test_implicit_base_edges_participate_in_cycles(odoo_project):
    project, _ = odoo_project
    addon(project, "example", [])
    addon(project, "base", ["example"])
    result = validate(project)
    assert result["reason"] == "DEPENDENCY_CYCLE"
    assert set(result["data"]["dependency_graph"]["cycle"]) == {"example", "base"}


def test_confirmed_cycle_takes_precedence_over_blocked_data_inspection(odoo_project):
    project, _ = odoo_project
    module = addon(project, "example", ["example"], data=["data.xml"])
    (module / "data.xml").write_text("<!DOCTYPE odoo []><odoo/>")
    result = validate(project)
    assert result["reason"] == "DEPENDENCY_CYCLE"
    assert result["data"]["xml_counts"]["blocked"] == 1


def test_incomplete_inventory_scan_leaves_graph_unchecked(odoo_project):
    project, _ = odoo_project
    result = validate(project, addons_paths=["addons", "absent"])
    assert result["reason"] == "MISSING_ADDONS"
    assert result["data"]["dependency_graph"]["status"] == "not_checked"
    assert result["data"]["dependency_graph"]["cycle"] == []


def test_long_cycle_retains_closed_witness_and_bounded_summary(odoo_project):
    project, _ = odoo_project
    names = ["example", *(f"a{i:03}" for i in range(499))]
    for index, name in enumerate(names):
        addon(project, name, [names[(index + 1) % len(names)]])
    result = validate(project)
    assert result["reason"] == "DEPENDENCY_CYCLE"
    cycle = result["data"]["dependency_graph"]["cycle"]
    assert len(cycle) == 501
    assert cycle[0] == cycle[-1]
    assert set(cycle) == set(names)
    assert len(result["summary"]) <= 4096


def test_cancellation_after_graph_analysis_does_not_claim_completion(odoo_project, monkeypatch):
    project, _ = odoo_project
    cancelled = Event()
    original = TopologicalSorter.prepare

    def prepare(sorter):
        original(sorter)
        cancelled.set()

    monkeypatch.setattr(TopologicalSorter, "prepare", prepare)
    result = create_service(project).execute("odoo.module.validate", cancellation=cancelled)[
        "result"
    ]
    assert result["status"] == "cancelled"
    assert not result["data"].get("inspection_complete", False)
