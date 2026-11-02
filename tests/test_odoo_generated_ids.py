"""Fresh-install outcomes for local XML IDs that no data file defines."""

import pytest
from mccann_hub.devkit.app import create_service

ACCESS = (
    "id,name,model_id:id,group_id:id,perm_read\n"
    "access_book,access_book,model_acme_book,base.group_user,1\n"
)
BOOK = """from odoo import fields, models


class Book(models.Model):
    _name = "acme.book"
    _description = "Book"

    title = fields.Char()
"""


def validate(odoo_project, files, *, manifest=None, arguments=None):
    project, module = odoo_project
    for name, content in files.items():
        path = module / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    data = [name for name in files if name.endswith((".xml", ".csv"))]
    (module / "__manifest__.py").write_text(
        repr({"name": "Example", "depends": ["base"], "data": data, **(manifest or {})})
    )
    return create_service(project).execute("odoo.module.validate", arguments)["result"]


def references(result):
    return [
        ref
        for kind in ("xml", "csv")
        for file in result["data"]["modules"][0][kind]["files"]
        for ref in file["references"]
    ]


def by_value(result, value):
    return next(ref for ref in references(result) if ref["value"] == value)


def test_model_ids_resolve_from_python_model_names(odoo_project):
    result = validate(
        odoo_project,
        {"models/book.py": BOOK, "security/ir.model.access.csv": ACCESS},
    )
    assert result["status"] == "success"
    ref = by_value(result, "model_acme_book")
    assert (ref["status"], ref["reason"]) == ("resolved", "orm_generated")
    assert ref["target"]["path"] == "models/book.py"


def test_field_ids_resolve_for_models_this_module_extends(odoo_project):
    result = validate(
        odoo_project,
        {
            "models/partner.py": (
                "from odoo import fields, models\n\n\n"
                "class Partner(models.Model):\n"
                "    _inherit = ['res.partner']\n\n"
                "    nickname = fields.Char()\n"
            ),
            "views.xml": """<odoo>
<record id="rule" model="x"><field name="field_id" ref="field_res_partner__nickname"/></record>
</odoo>""",
        },
    )
    assert result["status"] == "success"
    assert by_value(result, "field_res_partner__nickname")["status"] == "resolved"


def test_fresh_install_fails_on_a_local_id_nothing_defines(odoo_project):
    result = validate(
        odoo_project,
        {
            "views.xml": """<odoo>
<record id="acme_book_action" model="ir.actions.act_window"/>
<menuitem id="menu" action="acme_book_action_typo"/>
</odoo>"""
        },
    )
    assert (result["status"], result["reason"]) == ("failed", "UNDEFINED_XML_ID")
    assert "views.xml:3:1: XML ID acme_book_action_typo is not defined" in result["summary"]
    assert by_value(result, "acme_book_action_typo")["status"] == "undefined"


def test_update_mode_keeps_an_undefined_local_id_unknown(odoo_project):
    result = validate(
        odoo_project,
        {"views.xml": '<odoo><menuitem id="menu" action="missing_action"/></odoo>'},
        arguments={"install_mode": "update"},
    )
    assert result["status"] == "success"
    assert by_value(result, "missing_action")["status"] == "unknown"


def test_data_cannot_use_an_id_that_only_demo_defines(odoo_project):
    result = validate(
        odoo_project,
        {
            "data.xml": (
                '<odoo><record id="a" model="x"><field name="b" ref="demo_b"/></record></odoo>'
            ),
            "demo.xml": '<odoo><record id="demo_b" model="x"/></odoo>',
        },
        manifest={"data": ["data.xml"], "demo": ["demo.xml"]},
    )
    assert (result["status"], result["reason"]) == ("failed", "INVALID_LOAD_ORDER")
    assert by_value(result, "demo_b")["status"] == "undefined"


@pytest.mark.parametrize(
    ("files", "manifest"),
    [
        pytest.param(
            {"models/book.py": BOOK.replace('"acme.book"', '"acme." + "book"')},
            {},
            id="non-literal-model-name",
        ),
        pytest.param({"models/book.py": "class Broken(:\n"}, {}, id="python-syntax-error"),
        pytest.param({}, {"pre_init_hook": "create_ids"}, id="pre-init-hook"),
    ],
)
def test_generated_ids_stay_unknown_when_python_sources_are_uncertain(
    odoo_project, files, manifest
):
    result = validate(
        odoo_project,
        {**files, "security/ir.model.access.csv": ACCESS},
        manifest=manifest,
    )
    assert result["status"] == "success"
    assert by_value(result, "model_acme_book")["status"] == "unknown"


def test_function_calls_do_not_hide_undefined_ids(odoo_project):
    result = validate(
        odoo_project,
        {
            "views.xml": """<odoo>
<function model="x" name="setup"/>
<menuitem id="menu" action="missing_action"/>
</odoo>"""
        },
    )
    assert result["reason"] == "UNDEFINED_XML_ID"


def test_unknown_loader_tags_keep_absent_ids_unknown(odoo_project):
    result = validate(
        odoo_project,
        {
            "views.xml": """<odoo>
<custom_loader id="maybe_defined"/>
<menuitem id="menu" action="maybe_defined"/>
</odoo>"""
        },
    )
    assert result["status"] == "success"
    assert by_value(result, "maybe_defined")["status"] == "unknown"


def test_update_mode_also_resolves_generated_ids(odoo_project):
    result = validate(
        odoo_project,
        {"models/book.py": BOOK, "security/ir.model.access.csv": ACCESS},
        arguments={"install_mode": "update"},
    )
    assert by_value(result, "model_acme_book")["reason"] == "orm_generated"


def test_field_ids_resolve_only_for_fields_the_module_declares(odoo_project):
    rule = """<odoo>
<record id="a" model="x"><field name="field_id" ref="field_acme_book__title"/></record>
<record id="b" model="x"><field name="field_id" ref="field_acme_book__title_typo"/></record>
</odoo>"""
    result = validate(odoo_project, {"models/book.py": BOOK, "rules.xml": rule})
    assert result["status"] == "success"
    declared = by_value(result, "field_acme_book__title")
    assert (declared["status"], declared["target"]["line"]) == ("resolved", 8)
    # The name may come from a mixin or parent model, so it is unknown, not undefined.
    typo = by_value(result, "field_acme_book__title_typo")
    assert (typo["status"], typo["reason"]) == ("unknown", "unverified_field_name")
