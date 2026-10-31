import json
from pathlib import Path

import pytest
from devkit.app import create_service


def inspect_csv(
    odoo_project, content, *, filename="res.partner.csv", extra=None, data=None, demo=None
):
    project, module = odoo_project
    files = {filename: content, **(extra or {})}
    for name, value in files.items():
        (module / name).write_bytes(value if isinstance(value, bytes) else value.encode())
    (module / "__manifest__.py").write_text(
        repr(
            {
                "name": "Example",
                "data": list(files) if data is None else data,
                "demo": demo or [],
            }
        )
    )
    envelope = create_service(project).execute("odoo.module.validate")
    assert json.loads(Path(envelope["evidence_path"]).read_text())["result"] == envelope["result"]
    return envelope["result"]


def csv_file(result):
    return result["data"]["modules"][0]["csv"]["files"][0]


def test_csv_ids_resolve_later_xml(odoo_project):
    result = inspect_csv(
        odoo_project,
        "id,name\ncompany,Acme\n",
        extra={
            "view.xml": """<odoo>
<record id="contact" model="res.partner">
<field name="parent_id" ref="company"/>
</record>
</odoo>""",
        },
    )
    assert result["status"] == "success"
    assert csv_file(result)["definitions"][0]["xml_id"] == "example.company"
    ref = result["data"]["modules"][0]["xml"]["files"][0]["references"][0]
    assert ref["status"] == "resolved"
    assert ref["target"] == {"path": "res.partner.csv", "phase": "data", "line": 2, "column": 1}


@pytest.mark.parametrize("header", ["parent_id:id", "parent_id/id"])
def test_csv_references_use_prior_rows_and_xml(odoo_project, header):
    result = inspect_csv(
        odoo_project,
        f"id,name,{header}\ncompany,Acme,old\ncontact,Person,company\n",
        extra={
            "first.xml": '<odoo><record id="old" model="res.partner"/></odoo>',
        },
        data=["first.xml", "res.partner.csv"],
    )
    assert result["status"] == "success"
    assert csv_file(result)["references"][0]["status"] == "resolved"
    assert result["data"]["csv_reference_counts"] == {"resolved": 2, "unknown": 0}
    assert csv_file(result)["references"][0]["target"]["path"] == "first.xml"


def test_quoted_multiline_rows_report_physical_start_line(odoo_project):
    result = inspect_csv(
        odoo_project, 'id,name\nfirst,"Acme, Inc.\nSecond line"\nsecond,"A ""quote"""\n'
    )
    file = csv_file(result)
    assert file["row_count"] == 2
    assert [d["line"] for d in file["definitions"]] == [2, 4]


def test_translation_only_rows_and_blank_ids_do_not_define_ids(odoo_project):
    result = inspect_csv(
        odoo_project, "id,name,name@fr\n,,Traduction\n,Anonymous,Anonyme\ncompany,Acme,Acme\n"
    )
    assert result["status"] == "success"
    assert csv_file(result)["row_count"] == 2
    assert [d["xml_id"] for d in csv_file(result)["definitions"]] == ["example.company"]


def test_repeated_and_foreign_ids_are_not_duplicate_defects(odoo_project):
    result = inspect_csv(
        odoo_project, "id,name\ncompany,Acme\ncompany,Updated\nbase.partner,External update\n"
    )
    assert result["status"] == "success"
    assert len(csv_file(result)["definitions"]) == 2
    assert csv_file(result)["references"][0]["reason"] == "external_module"


def test_forward_and_ambiguous_reference_cells_remain_unknown(odoo_project):
    result = inspect_csv(odoo_project, 'id,parent_id:id\nfirst,later\nlater,\nlast,"first,later"\n')
    assert result["status"] == "success"
    assert [r["reason"] for r in csv_file(result)["references"]] == [
        "forward_definition",
        "unsupported_literal",
    ]


@pytest.mark.parametrize("content", [b"", b"id,name\nitem,\xff\n"], ids=["empty", "invalid-utf8"])
def test_confirmed_loader_input_defects_fail(odoo_project, content):
    result = inspect_csv(odoo_project, content)
    assert result["status"] == "failed"
    assert result["reason"] == "INVALID_CSV"


@pytest.mark.parametrize(
    "content",
    [
        'id,name\nitem,"unfinished',
        "id,id\nfirst,second\n",
        "id,parent:id,parent/id\nitem,a,b\n",
        "id,name\nitem\n",
        "id,child_ids/name\nitem,child\n",
        "\ufeffid,name\nitem,Name\n",
    ],
    ids=["quoting", "duplicate-id", "alias-collision", "short-row", "nested-path", "bom"],
)
def test_unsupported_csv_layouts_block_without_partial_definitions(odoo_project, content):
    result = inspect_csv(odoo_project, content)
    assert result["status"] == "blocked"
    assert result["reason"] == "CSV_UNSUPPORTED"
    assert csv_file(result)["definitions"] == []


def test_csv_without_id_is_valid_but_does_not_invent_identity(odoo_project):
    result = inspect_csv(odoo_project, "name\nAnonymous\n")
    assert result["status"] == "success"
    assert csv_file(result)["definitions"] == []


def test_demo_csv_cannot_resolve_a_data_reference(odoo_project):
    result = inspect_csv(
        odoo_project,
        "id,name\ncompany,Acme\n",
        extra={
            "first.xml": """<odoo>
<record id="item" model="x">
<field name="parent" ref="company"/>
</record>
</odoo>""",
        },
        data=["first.xml"],
        demo=["res.partner.csv"],
    )
    ref = result["data"]["modules"][0]["xml"]["files"][0]["references"][0]
    assert ref["reason"] == "demo_only_definition"


def test_invalid_csv_cannot_establish_identity_for_later_xml(odoo_project):
    result = inspect_csv(
        odoo_project,
        "id,name\ncompany,Acme\nbad\n",
        extra={
            "last.xml": """<odoo>
<record id="item" model="x">
<field name="parent" ref="company"/>
</record>
</odoo>""",
        },
    )
    assert result["status"] == "blocked"
    assert csv_file(result)["definitions"] == []
    assert result["data"]["modules"][0]["xml"]["files"][0]["references"][0]["status"] == "unknown"


def test_csv_cells_are_never_executed_or_returned_as_record_values(odoo_project):
    project, _ = odoo_project
    result = inspect_csv(
        odoo_project, 'id,name\nitem,__import__("pathlib").Path("executed").touch()\n'
    )
    assert result["status"] == "success"
    assert not (project / "executed").exists()
    assert "__import__" not in json.dumps(result)


@pytest.mark.parametrize(
    "content",
    [
        b"id,name\n" + b"x" * 1_048_576,
        b"name\n" + b"x" * 65_537,
        b"name\n" + b"\n" * 10_001,
        ",".join("field_" + str(i) for i in range(129)).encode() + b"\n",
        ("id\n" + "\n".join("record_" + str(i) for i in range(4001))).encode(),
    ],
    ids=["bytes", "field", "rows", "columns", "events"],
)
def test_csv_limits_block_and_discard_partial_identity(odoo_project, content):
    result = inspect_csv(odoo_project, content)
    assert result["status"] == "blocked"
    assert result["reason"] == "CSV_LIMIT"
    assert csv_file(result)["definitions"] == []
    assert not result["data"]["modules"][0]["csv"]["complete"]


@pytest.mark.parametrize(
    "count,content",
    [
        (257, "id,name\nitem,Name\n"),
        (18, "name\n" + ("x" * 60_000 + "\n") * 16),
    ],
    ids=["files", "total-bytes"],
)
def test_csv_invocation_budget_spans_files(odoo_project, count, content):
    result = inspect_csv(odoo_project, content, data=["res.partner.csv"] * count)
    assert result["status"] == "blocked"
    assert result["reason"] == "CSV_LIMIT"
    assert result["data"]["csv_counts"]["valid"] > 0
    assert result["data"]["csv_counts"]["blocked"] > 0


def test_missing_and_unsafe_csv_paths_do_not_produce_definitions(odoo_project, tmp_path):
    project, module = odoo_project
    outside = tmp_path / "private.csv"
    outside.write_text("id,name\nsecret,Private\n")
    (module / "escape.csv").symlink_to(outside)
    (module / "__manifest__.py").write_text(repr({"name": "Example", "data": ["escape.csv"]}))
    result = create_service(project).execute("odoo.module.validate")["result"]
    assert result["reason"] == "INVALID_MANIFEST"
    assert result["data"]["modules"][0]["csv"]["files"] == []
    assert "secret" not in json.dumps(result)


def test_unreadable_csv_blocks_instead_of_claiming_a_defect(odoo_project, monkeypatch):
    project, module = odoo_project
    target = module / "res.partner.csv"
    target.write_text("id,name\nitem,Name\n")
    (module / "__manifest__.py").write_text(repr({"name": "Example", "data": ["res.partner.csv"]}))
    original = Path.open

    def inaccessible(path, *args, **kwargs):
        if path == target:
            raise PermissionError("test denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", inaccessible)
    result = create_service(project).execute("odoo.module.validate")["result"]
    assert result["reason"] == "CSV_UNAVAILABLE"
    assert result["status"] == "blocked"


def test_csv_parser_does_not_change_global_field_limit(odoo_project):
    import csv

    before = csv.field_size_limit()
    result = inspect_csv(odoo_project, "id,name\nitem,Name\n")
    assert result["status"] == "success"
    assert csv.field_size_limit() == before


def test_empty_and_translation_only_rows_are_ignored_before_width_checks(odoo_project):
    result = inspect_csv(odoo_project, 'id,name,name@fr\n""\n,,,,\n,,Traduction\nitem,Name,Nom\n')
    assert result["status"] == "success"
    assert csv_file(result)["row_count"] == 1


def test_csv_findings_obey_the_existing_result_budget(odoo_project):
    content = "id\n" + "\n".join(f"item_{i}_" + "a" * 300 for i in range(2000))
    result = inspect_csv(odoo_project, content)
    assert result["status"] == "error"
    assert result["reason"] == "RESULT_LIMIT"
    assert not result["data"]["inspection_complete"]
