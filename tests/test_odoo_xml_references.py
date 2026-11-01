import pytest
from mccann_hub.devkit.app import create_service


def inspect(odoo_project, files, *, data=None, demo=None):
    project, module = odoo_project
    for name, content in files.items():
        (module / name).write_text(content)
    (module / "__manifest__.py").write_text(
        repr(
            {
                "name": "Example",
                "data": list(files) if data is None else data,
                "demo": demo or [],
            }
        )
    )
    result = create_service(project).execute("odoo.module.validate")["result"]
    return result, result["data"]["modules"][0]["xml"]


def references(xml):
    return [ref for file in xml["files"] for ref in file["references"]]


def test_local_definitions_resolve_in_file_and_manifest_order(odoo_project):
    result, xml = inspect(
        odoo_project,
        {
            "first.xml": '<odoo>\n<record id="parent" model="x"/>\n</odoo>',
            "second.xml": """<odoo>
<record id="child" model="x">
<field name="parent" ref="parent"/>
</record>
</odoo>""",
        },
    )
    assert result["status"] == "success"
    ref = references(xml)[0]
    assert (ref["xml_id"], ref["status"]) == ("example.parent", "resolved")
    assert ref["target"] == {"path": "first.xml", "phase": "data", "line": 2, "column": 1}


def test_forward_and_external_ids_are_unknown_not_missing(odoo_project):
    result, xml = inspect(
        odoo_project,
        {
            "views.xml": """<odoo>
<record id="first" model="x">
<field name="later" ref="later"/>
<field name="external" ref="base.partner"/>
</record>
<record id="later" model="x"/>
</odoo>"""
        },
    )
    assert result["status"] == "success"
    assert [r["reason"] for r in references(xml)] == ["forward_definition", "external_module"]
    assert all(r["status"] == "unknown" for r in references(xml))


def test_data_does_not_resolve_from_demo_but_demo_can_use_data(odoo_project):
    _, xml = inspect(
        odoo_project,
        {
            "data.xml": """<odoo>
<record id="data" model="x">
<field name="demo" ref="demo"/>
</record>
</odoo>""",
            "demo.xml": """<odoo>
<record id="demo" model="x">
<field name="data" ref="data"/>
</record>
</odoo>""",
        },
        data=["data.xml"],
        demo=["demo.xml"],
    )
    assert [(r["status"], r["reason"]) for r in references(xml)] == [
        ("unknown", "demo_only_definition"),
        ("resolved", "earlier_local_definition"),
    ]


def test_repeated_ids_are_updates_and_self_reference_needs_prior_definition(odoo_project):
    result, xml = inspect(
        odoo_project,
        {
            "views.xml": """<odoo>
<record id="item" model="x"><field name="self" ref="item"/></record>
<record id="item" model="x"><field name="self" ref="item"/></record>
</odoo>"""
        },
    )
    assert result["status"] == "success"
    assert [r["status"] for r in references(xml)] == ["unknown", "resolved"]
    assert len(xml["files"][0]["definitions"]) == 2


@pytest.mark.parametrize(
    "operation", ['<delete model="x" id="parent"/>', '<function model="x" name="change"/>']
)
def test_dynamic_operations_interrupt_resolution(odoo_project, operation):
    _, xml = inspect(
        odoo_project,
        {
            "views.xml": '<odoo><record id="parent" model="x"/>'
            + operation
            + '<record id="child" model="x"><field name="parent" ref="parent"/></record></odoo>'
        },
    )
    assert references(xml)[0]["status"] == "unknown"
    assert references(xml)[0]["reason"] == "unverified_effects"
    assert xml["files"][0]["unexamined"]


def test_csv_update_between_xml_files_supplies_latest_literal_definition(odoo_project):
    _, xml = inspect(
        odoo_project,
        {
            "first.xml": '<odoo><record id="parent" model="x"/></odoo>',
            "data.csv": "id,name\nparent,Updated\n",
            "last.xml": """<odoo>
<record id="child" model="x">
<field name="parent" ref="parent"/>
</record>
</odoo>""",
        },
    )
    assert references(xml)[0]["status"] == "resolved"
    assert references(xml)[0]["target"]["path"] == "data.csv"
    assert not xml["skipped_files"]


def test_template_content_is_not_mistaken_for_loader_operations(odoo_project):
    _, xml = inspect(
        odoo_project,
        {
            "views.xml": """<odoo>
<template id="layout"><record id="html_id"/><field ref="html_reference"/></template>
<record id="view" model="x">
<field name="arch" type="xml">
<record id="nested"/>
<field ref="nested_ref"/>
</field>
</record>
<record id="consumer" model="x"><field name="parent" ref="html_id"/></record>
</odoo>"""
        },
    )
    assert [d["xml_id"] for d in xml["files"][0]["definitions"]] == [
        "example.layout",
        "example.view",
        "example.consumer",
    ]
    assert len(references(xml)) == 1
    assert references(xml)[0]["reason"] == "not_in_scanned_xml"


def test_menu_and_template_literal_attributes(odoo_project):
    _, xml = inspect(
        odoo_project,
        {
            "views.xml": """<odoo>
<record id="action" model="ir.actions.act_window"/>
<menuitem id="root"/>
<menuitem id="child" parent="root" action="example.action"/>
<template id="layout"/>
<template id="extension" inherit_id="layout"/>
</odoo>"""
        },
    )
    assert len(references(xml)) == 3
    assert all(r["status"] == "resolved" for r in references(xml))


def test_external_updates_do_not_define_local_or_external_ids(odoo_project):
    _, xml = inspect(
        odoo_project,
        {
            "views.xml": """<odoo>
<record id="base.partner" model="x"/>
<record id="local" model="x"><field name="external" ref="base.partner"/></record>
</odoo>"""
        },
    )
    assert [d["xml_id"] for d in xml["files"][0]["definitions"]] == ["example.local"]
    assert all(r["status"] == "unknown" for r in references(xml))


def test_conditional_definition_cannot_establish_reference_presence(odoo_project):
    _, xml = inspect(
        odoo_project,
        {
            "views.xml": """<odoo>
<record id="maybe" model="x" forcecreate="False"/>
<record id="child" model="x"><field name="parent" ref="maybe"/></record>
</odoo>"""
        },
    )
    assert references(xml)[0]["reason"] == "conditional_definition"


def test_invalid_xml_does_not_contribute_partial_definitions(odoo_project):
    result, xml = inspect(
        odoo_project,
        {
            "bad.xml": '<odoo><record id="parent" model="x"/>',
            "good.xml": """<odoo>
<record id="child" model="x">
<field name="parent" ref="parent"/>
</record>
</odoo>""",
        },
    )
    assert result["status"] == "failed"
    assert xml["files"][0]["definitions"] == []
    assert references(xml)[0]["status"] == "unknown"


def test_eval_is_reported_without_execution(odoo_project):
    project, _ = odoo_project
    result, xml = inspect(
        odoo_project,
        {
            "views.xml": """<odoo>
<record id="value" model="x">
<field name="value" eval="__import__('pathlib').Path('executed').touch()"/>
</record>
</odoo>"""
        },
    )
    assert result["status"] == "success"
    assert not (project / "executed").exists()
    assert xml["files"][0]["unexamined"][0]["reason"] == "dynamic_field_value"


def test_reference_event_budget_blocks_without_partial_resolution(odoo_project):
    result, xml = inspect(
        odoo_project,
        {
            "views.xml": "<odoo>"
            + "".join(f'<record id="item_{i}" model="x"/>' for i in range(4001))
            + "</odoo>"
        },
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "XML_LIMIT"
    assert xml["files"][0]["definitions"] == []
    assert xml["reference_counts"] == {"resolved": 0, "unknown": 0}


def test_declared_xml_extension_applies_to_contained_symlink(odoo_project):
    project, module = odoo_project
    (module / "payload.txt").write_text("<odoo>")
    (module / "views.xml").symlink_to("payload.txt")
    (module / "__manifest__.py").write_text(repr({"name": "Example", "data": ["views.xml"]}))
    result = create_service(project).execute("odoo.module.validate")["result"]
    assert result["reason"] == "INVALID_XML"


def test_unseen_reference_stays_unknown_under_complete_module_inventory(odoo_project):
    project, module = odoo_project
    (module / "views.xml").write_text(
        '<odoo><record id="x" model="x"><field name="p" ref="unseen"/></record></odoo>'
    )
    (module / "__manifest__.py").write_text(
        repr({"name": "Example", "depends": ["base"], "data": ["views.xml"]})
    )
    base = project / "addons/base"
    base.mkdir()
    (base / "__manifest__.py").write_text("{'name': 'Base', 'depends': []}")
    result = create_service(project).execute(
        "odoo.module.validate", {"inventory": {"complete": True}, "strict_dependencies": True}
    )["result"]
    assert result["status"] == "success"
    assert result["data"]["xml_reference_counts"] == {"resolved": 0, "unknown": 1}
