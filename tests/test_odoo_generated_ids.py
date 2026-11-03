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


BOOK_IMPORTS = {
    "__init__.py": "from . import models\n",
    "models/__init__.py": "from . import book\n",
}
BOOK_FILES = {**BOOK_IMPORTS, "models/book.py": BOOK}


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
        {**BOOK_FILES, "security/ir.model.access.csv": ACCESS},
    )
    assert result["status"] == "success"
    ref = by_value(result, "model_acme_book")
    assert (ref["status"], ref["reason"]) == ("resolved", "orm_generated")
    assert ref["target"]["path"] == "models/book.py"


def test_field_ids_resolve_for_models_this_module_extends(odoo_project):
    result = validate(
        odoo_project,
        {
            "__init__.py": "from .models import partner\n",
            "models/__init__.py": "",
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
        {**BOOK_IMPORTS, **files, "security/ir.model.access.csv": ACCESS},
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
        {**BOOK_FILES, "security/ir.model.access.csv": ACCESS},
        arguments={"install_mode": "update"},
    )
    assert by_value(result, "model_acme_book")["reason"] == "orm_generated"


def test_field_ids_resolve_only_for_fields_the_module_declares(odoo_project):
    rule = """<odoo>
<record id="a" model="x"><field name="field_id" ref="field_acme_book__title"/></record>
<record id="b" model="x"><field name="field_id" ref="field_acme_book__title_typo"/></record>
</odoo>"""
    result = validate(odoo_project, {**BOOK_FILES, "rules.xml": rule})
    assert result["status"] == "success"
    declared = by_value(result, "field_acme_book__title")
    assert (declared["status"], declared["target"]["line"]) == ("resolved", 8)
    # The name may come from a mixin or parent model, so it is unknown, not undefined.
    typo = by_value(result, "field_acme_book__title_typo")
    assert (typo["status"], typo["reason"]) == ("unknown", "unverified_field_name")


def test_field_ids_resolve_when_the_model_name_contains_a_double_underscore(odoo_project):
    rule = """<odoo>
<record id="a" model="x"><field name="field_id" ref="field_acme__book__title"/></record>
</odoo>"""
    book = BOOK.replace('"acme.book"', '"acme__book"')
    result = validate(odoo_project, {**BOOK_FILES, "models/book.py": book, "rules.xml": rule})
    assert result["status"] == "success"
    assert by_value(result, "field_acme__book__title")["status"] == "resolved"


@pytest.mark.parametrize("local_id", ["model_acme_book", "field_acme_book__title"])
@pytest.mark.parametrize("root_imports", [None, "", "from . import models\n"])
def test_unimported_models_do_not_generate_ids(odoo_project, local_id, root_imports):
    files = {
        "models/__init__.py": "",
        "models/book.py": BOOK,
        "security/ir.model.access.csv": ACCESS.replace("model_acme_book", local_id),
    }
    if root_imports is not None:
        files["__init__.py"] = root_imports
    result = validate(odoo_project, files)
    assert (result["status"], result["reason"]) == ("failed", "UNDEFINED_XML_ID")
    assert by_value(result, local_id)["status"] == "undefined"


@pytest.mark.parametrize(
    "root_imports",
    [
        "from . import models as catalog\n",
        "from .models import book as catalog\n",
        "from .models.book import Book\n",
    ],
)
def test_relative_import_forms_register_models(odoo_project, root_imports):
    result = validate(
        odoo_project,
        {**BOOK_FILES, "__init__.py": root_imports, "security/ir.model.access.csv": ACCESS},
    )
    assert by_value(result, "model_acme_book")["reason"] == "orm_generated"


@pytest.mark.parametrize(
    "root_imports",
    [
        "import importlib\nimportlib.import_module('.models.book', __name__)\n",
        "from importlib import import_module as load\nload('.models.book', __name__)\n",
        "__import__(__name__ + '.models.book')\n",
        "from .models import *\n",
        "if enabled:\n    from .models import book\n",
        "from . import missing\n",
        "import odoo.addons.example.models.book\n",
        "from odoo.addons.example.models import book\n",
    ],
)
def test_unfollowed_imports_keep_generated_ids_unknown(odoo_project, root_imports):
    result = validate(
        odoo_project,
        {
            **BOOK_FILES,
            "__init__.py": root_imports,
            "models/__init__.py": "",
            "security/ir.model.access.csv": ACCESS,
        },
    )
    reference = by_value(result, "model_acme_book")
    assert result["status"] == "success"
    assert reference["status"] == "unknown"
    assert reference["target"] is None


def test_relative_parent_imports_and_cycles_terminate(odoo_project):
    result = validate(
        odoo_project,
        {
            **BOOK_FILES,
            "models/__init__.py": "from ..catalog import book\n",
            "catalog/__init__.py": "from .. import models\n",
            "catalog/book.py": BOOK,
            "security/ir.model.access.csv": ACCESS,
        },
    )
    reference = by_value(result, "model_acme_book")
    assert (reference["status"], reference["reason"]) == ("resolved", "orm_generated")
    assert reference["target"]["path"] == "catalog/book.py"


def test_unimported_python_errors_do_not_hide_undefined_ids(odoo_project):
    result = validate(
        odoo_project,
        {
            "__init__.py": "",
            "unused.py": "class Broken(:\n",
            "security/ir.model.access.csv": ACCESS,
        },
    )
    assert by_value(result, "model_acme_book")["status"] == "undefined"


def test_update_mode_keeps_unimported_model_ids_unknown(odoo_project):
    result = validate(
        odoo_project,
        {"__init__.py": "", "models/book.py": BOOK, "security/ir.model.access.csv": ACCESS},
        arguments={"install_mode": "update"},
    )
    assert by_value(result, "model_acme_book")["status"] == "unknown"


@pytest.mark.parametrize("limit", ["files", "file_bytes", "total_bytes"])
def test_import_scan_limits_keep_generated_ids_unknown(odoo_project, monkeypatch, limit):
    from mccann_hub.devkit_odoo import python_inspection

    monkeypatch.setitem(python_inspection.LIMITS, limit, 1)
    result = validate(odoo_project, {**BOOK_FILES, "security/ir.model.access.csv": ACCESS})
    assert result["status"] == "success"
    assert by_value(result, "model_acme_book")["status"] == "unknown"


def test_imported_sources_are_not_executed(odoo_project):
    project, _ = odoo_project
    marker = project / "executed"
    result = validate(
        odoo_project,
        {
            **BOOK_FILES,
            "models/book.py": f"from pathlib import Path\nPath({str(marker)!r}).touch()\n" + BOOK,
            "security/ir.model.access.csv": ACCESS,
        },
    )
    assert by_value(result, "model_acme_book")["status"] == "resolved"
    assert not marker.exists()


@pytest.mark.parametrize("directory", [False, True])
def test_imports_cannot_follow_escaping_symlinks(odoo_project, tmp_path, directory):
    _, module = odoo_project
    external = tmp_path / "external"
    external.mkdir()
    (external / "__init__.py").write_text(BOOK)
    target = external if directory else external / "__init__.py"
    link = module / ("book" if directory else "book.py")
    link.symlink_to(target, target_is_directory=directory)
    result = validate(
        odoo_project,
        {"__init__.py": "from . import book\n", "security/ir.model.access.csv": ACCESS},
    )
    reference = by_value(result, "model_acme_book")
    assert (reference["status"], reference["target"]) == ("unknown", None)
