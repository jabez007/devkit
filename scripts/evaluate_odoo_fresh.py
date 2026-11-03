"""Evaluate fresh-install references on clean, pinned public OCA snapshots.

Original checkouts are read-only inputs. Each planted defect changes one copied
addon, then restores the changed file before the next trial. No addon is executed.
"""

import argparse
import csv
import io
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from mccann_hub.devkit_odoo.cli import parser, validate_addons
from mccann_hub.devkit_odoo.validation import read_manifest

SNAPSHOTS = {
    "server-tools": "389daeb98a8e21fe11594bdddef873bb07d0cb61",
    "sale-workflow": "b2cb74591c66882b91264106abc5229e200f5bff",
}


def git(project, *args):
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(project), "-c", "core.fsmonitor=false", *args],
        text=True,
    ).strip()


def validate(project, module=None):
    args = ["--project", str(project), "--addons-path", "."]
    if module:
        args += ["--module", module]
    return validate_addons(parser().parse_args(args))


def references(module):
    for kind in ("xml", "csv"):
        for file in module[kind]["files"]:
            for reference in file["references"]:
                yield kind, file, reference


def baseline(name, project):
    assert git(project, "rev-parse", "HEAD") == SNAPSHOTS[name], f"Wrong snapshot: {name}"
    assert not git(project, "status", "--porcelain"), f"Dirty snapshot: {name}"
    result = validate(project)
    assert result.status == "success", result.summary
    counts = Counter()
    unknown = Counter()
    for module in result.data["modules"]:
        for _, _, reference in references(module):
            counts[reference["reason"]] += 1
            if reference["status"] == "unknown" and reference["reason"] != "external_module":
                unknown[reference["reason"]] += 1
    return result.data["modules"], {
        "repository": name,
        "revision": SNAPSHOTS[name],
        "modules": len(result.data["modules"]),
        "status": result.status,
        "generated_ids_resolved": counts["orm_generated"],
        "unknown_local_references": dict(unknown),
    }


def xml_typo(path, reference):
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    start = sum(map(len, lines[: reference["line"] - 1])) + reference["column"] - 1
    value = reference["value"]
    attribute = re.escape(reference["attribute"])
    pattern = re.compile(rf"(\b{attribute}\s*=\s*)([\"']){re.escape(value)}\2")
    tail, count = pattern.subn(
        lambda match: f"{match[1]}{match[2]}{value}_typo{match[2]}", text[start:], count=1
    )
    assert count == 1, (path, reference)
    return (text[:start] + tail).encode()


def csv_typo(path, reference):
    source = csv.reader(io.StringIO(path.read_text()))
    rows = []
    matched = False
    start = 1
    for row in source:
        if start == reference["line"]:
            column = reference["column"] - 1
            assert row[column] == reference["value"]
            row[column] += "_typo"
            matched = True
        rows.append(row)
        start = source.line_num + 1
    assert matched, (path, reference)
    output = io.StringIO()
    csv.writer(output).writerows(rows)
    return output.getvalue().encode()


def trial(project, module, path, content):
    original = path.read_bytes()
    try:
        path.write_bytes(content)
        return validate(project, module)
    finally:
        path.write_bytes(original)


def record(counts, result, reason):
    assert result.status in {"success", "failed"}, result.summary
    caught = result.status == "failed" and result.reason == reason
    assert caught or result.status == "success", result.summary
    counts["planted"] += 1
    counts["caught"] += caught
    if not caught:
        counts["uncaught_modules"][result.data["modules"][0]["module"]] += 1


def typo_trials(project, module, counts):
    seen = set()
    for kind, file, reference in references(module):
        key = (file["path"], reference["value"])
        if reference["status"] != "resolved" or key in seen:
            continue
        seen.add(key)
        path = project / module["path"] / file["path"]
        content = xml_typo(path, reference) if kind == "xml" else csv_typo(path, reference)
        result = trial(project, module["module"], path, content)
        record(counts, result, "UNDEFINED_XML_ID")


def order_trials(project, module, counts):
    path = project / module["path"] / "__manifest__.py"
    manifest = read_manifest(path.parent)
    seen = set()
    for _, file, reference in references(module):
        if reference["reason"] != "earlier_local_definition":
            continue
        target = reference["target"]
        pair = (file["path"], target["path"])
        if file["phase"] != target["phase"] or pair[0] == pair[1] or pair in seen:
            continue
        seen.add(pair)
        phase = file["phase"]
        files = list(manifest[phase])
        first, second = files.index(pair[0]), files.index(pair[1])
        files[first], files[second] = files[second], files[first]
        content = repr({**manifest, phase: files}).encode()
        result = trial(project, module["module"], path, content)
        record(counts, result, "INVALID_LOAD_ORDER")


def import_trial(project, module, counts):
    if not any(ref["reason"] == "orm_generated" for _, _, ref in references(module)):
        return
    path = project / module["path"] / "__init__.py"
    result = trial(project, module["module"], path, b"")
    generated = [ref for _, _, ref in references(result.data["modules"][0])]
    assert not any(ref["reason"] == "orm_generated" for ref in generated), module["module"]
    record(counts, result, "UNDEFINED_XML_ID")


def evaluate(projects):
    reports = []
    counts = {
        name: {"planted": 0, "caught": 0, "uncaught_modules": Counter()}
        for name in ("load_order", "typos", "imports")
    }
    with tempfile.TemporaryDirectory(prefix="devkit-odoo-fresh-evaluation-") as temporary:
        for name, original in projects.items():
            modules, report = baseline(name, original)
            reports.append(report)
            project = Path(temporary) / name
            for module in modules:
                destination = project / module["path"]
                shutil.copytree(original / module["path"], destination)
                typo_trials(project, module, counts["typos"])
                order_trials(project, module, counts["load_order"])
                import_trial(project, module, counts["imports"])
            assert not git(original, "status", "--porcelain"), f"Snapshot changed: {name}"
    return {"snapshots": reports, "mutations": counts}


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--server-tools", type=Path, required=True)
    arguments.add_argument("--sale-workflow", type=Path, required=True)
    args = arguments.parse_args()
    projects = {
        "server-tools": args.server_tools.resolve(),
        "sale-workflow": args.sale_workflow.resolve(),
    }
    print(json.dumps(evaluate(projects), indent=2))


if __name__ == "__main__":
    main()
