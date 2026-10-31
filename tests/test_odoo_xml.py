import json
from pathlib import Path

import pytest
from devkit.app import create_service


def validate_xml(odoo_project, content, *, phase="data", filename="views.xml"):
    project, module = odoo_project
    (module / "__manifest__.py").write_text(repr({"name": "Example", phase: [filename]}))
    (module / filename).write_bytes(content if isinstance(content, bytes) else content.encode())
    envelope = create_service(project).execute("odoo.module.validate")
    assert json.loads(Path(envelope["evidence_path"]).read_text())["result"] == envelope["result"]
    return envelope["result"]


def test_malformed_xml_reports_file_and_location(odoo_project):
    result = validate_xml(odoo_project, '<odoo>\n<record id="bad">\n</odoo>')
    assert result["status"] == "failed"
    assert result["reason"] == "INVALID_XML"
    finding = result["data"]["modules"][0]["xml"]["files"][0]
    assert finding["path"] == "views.xml"
    assert finding["line"] == 3
    assert finding["column"] >= 1
    assert "views.xml:3:" in result["summary"]


@pytest.mark.parametrize("phase", ["data", "demo"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "iso-8859-1"])
def test_xml_encodings_and_phases(odoo_project, phase, encoding):
    xml = f'<?xml version="1.0" encoding="{encoding}"?><odoo><!-- café --></odoo>'
    result = validate_xml(odoo_project, xml.encode(encoding), phase=phase)
    assert result["status"] == "success"
    finding = result["data"]["modules"][0]["xml"]["files"][0]
    assert finding["status"] == "valid"
    assert finding["phase"] == phase
    assert result["data"]["xml_counts"] == {"valid": 1, "invalid": 0, "blocked": 0}


@pytest.mark.parametrize(
    "declaration",
    [
        '<!DOCTYPE odoo SYSTEM "https://example.invalid/external.dtd">',
        '<!DOCTYPE odoo [<!ENTITY secret SYSTEM "file:///etc/passwd">]>',
        '<!DOCTYPE odoo [<!ENTITY a "amplify"><!ENTITY b "&a;&a;&a;">]>',
    ],
)
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_dtds_are_blocked_without_resolution(odoo_project, declaration, encoding):
    content = f'<?xml version="1.0" encoding="{encoding}"?>{declaration}<odoo/>'
    result = validate_xml(odoo_project, content.encode(encoding))
    assert result["status"] == "blocked"
    assert result["reason"] == "XML_UNSUPPORTED"
    assert "DTD" in result["summary"]
    assert not result["data"]["modules"][0]["xml"]["complete"]


@pytest.mark.parametrize(
    "content",
    [
        "<odoo>" + "x" * 1_048_576 + "</odoo>",
        "<odoo>" + "<data>" * 129 + "</data>" * 129 + "</odoo>",
        "<odoo>" + "<record/>" * 100_001 + "</odoo>",
    ],
    ids=["file-bytes", "depth", "elements"],
)
def test_xml_bounds_report_missing_coverage(odoo_project, content):
    result = validate_xml(odoo_project, content)
    assert result["status"] == "blocked"
    assert result["reason"] == "XML_LIMIT"
    assert result["data"]["xml_counts"]["blocked"] == 1


def test_unknown_encoding_is_not_a_confirmed_xml_defect(odoo_project):
    result = validate_xml(odoo_project, '<?xml version="1.0" encoding="unknown"?><odoo/>')
    assert result["status"] == "blocked"
    assert result["reason"] == "XML_UNSUPPORTED"


def test_declared_non_xml_is_not_parsed(odoo_project):
    result = validate_xml(odoo_project, "id,name\nitem,Example\n", filename="data.csv")
    assert result["status"] == "success"
    assert result["data"]["modules"][0]["xml"]["files"] == []


@pytest.mark.parametrize("count,size", [(257, 7), (17, 1_000_000)], ids=["files", "total-bytes"])
def test_xml_invocation_budget_is_shared_across_files(odoo_project, count, size):
    project, module = odoo_project
    (module / "many.xml").write_text("<odoo>" + " " * (size - 7) + "</odoo>")
    (module / "__manifest__.py").write_text(repr({"name": "Example", "data": ["many.xml"] * count}))
    result = create_service(project).execute("odoo.module.validate")["result"]
    assert result["status"] == "blocked"
    assert result["reason"] == "XML_LIMIT"
    assert result["data"]["xml_counts"]["valid"] > 0
    assert result["data"]["xml_counts"]["blocked"] > 0


def test_xml_failures_and_blocked_files_are_both_preserved(odoo_project):
    project, module = odoo_project
    (module / "bad.xml").write_text("<odoo>")
    (module / "dtd.xml").write_text("<!DOCTYPE odoo><odoo/>")
    (module / "__manifest__.py").write_text(
        repr({"name": "Example", "data": ["bad.xml", "dtd.xml"]})
    )
    result = create_service(project).execute("odoo.module.validate")["result"]
    assert result["status"] == "failed"
    assert result["reason"] == "INVALID_XML"
    assert result["data"]["xml_counts"] == {"valid": 0, "invalid": 1, "blocked": 1}


def test_unreadable_xml_blocks_without_claiming_a_defect(odoo_project, monkeypatch):
    project, module = odoo_project
    target = module / "views.xml"
    target.write_text("<odoo/>")
    (module / "__manifest__.py").write_text(repr({"name": "Example", "data": ["views.xml"]}))
    original = Path.open

    def inaccessible(path, *args, **kwargs):
        if path == target:
            raise PermissionError("test access denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", inaccessible)
    result = create_service(project).execute("odoo.module.validate")["result"]
    assert result["status"] == "blocked"
    assert result["reason"] == "XML_UNAVAILABLE"


@pytest.mark.parametrize(
    "filename,content",
    [
        ("views.xml", b"<odoo/>"),
        ("res.partner.csv", b"id,name\nitem,Name\n"),
    ],
)
def test_cancellation_after_data_read_does_not_claim_inspection_complete(
    odoo_project, monkeypatch, filename, content
):
    from io import BytesIO
    from threading import Event

    project, module = odoo_project
    target = module / filename
    target.write_bytes(content)
    (module / "__manifest__.py").write_text(repr({"name": "Example", "data": [filename]}))
    cancelled = Event()
    original = Path.open

    class CancelOnRead(BytesIO):
        def read(self, *args):
            content = super().read(*args)
            cancelled.set()
            return content

    def open_xml(path, *args, **kwargs):
        return CancelOnRead(content) if path == target else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_xml)
    envelope = create_service(project).execute("odoo.module.validate", cancellation=cancelled)
    result = envelope["result"]
    assert result["status"] == "cancelled"
    assert result["reason"] == "CANCELLED"
    assert result["data"] == {}
    assert json.loads(Path(envelope["evidence_path"]).read_text())["result"] == result


@pytest.mark.parametrize("encoding", ["utf-32", "utf-32-le", "utf-32-be"])
def test_unsupported_utf32_is_blocked_not_reported_as_malformed(odoo_project, encoding):
    result = validate_xml(
        odoo_project, '<?xml version="1.0" encoding="utf-32"?><odoo/>'.encode(encoding)
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "XML_UNSUPPORTED"
