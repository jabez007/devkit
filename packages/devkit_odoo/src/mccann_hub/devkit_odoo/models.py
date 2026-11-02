"""Model names declared by an addon's Python sources, read with ast and never imported.

Odoo creates ``<module>.model_<name>`` and ``<module>.field_<name>__<field>`` IDs when
it registers the models a module defines or extends. Those IDs exist before any data
file loads, so data files can reference them without defining them.
"""

import ast
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mccann_hub.devkit.contracts import JSONObject

LIMITS = {"files": 1000, "file_bytes": 1_048_576, "total_bytes": 16_777_216}


@dataclass
class ModelIndex:
    """Generated-ID targets; ``complete`` is false when any model name was unreadable."""

    targets: dict[str, JSONObject] = field(default_factory=dict)
    complete: bool = True

    def target(self, local_id: str) -> JSONObject | None:
        if local_id.startswith("model_"):
            return self.targets.get(local_id.removeprefix("model_"))
        if local_id.startswith("field_") and "__" in local_id:
            return self.targets.get(local_id.removeprefix("field_").split("__", 1)[0])
        return None


def scan_models(module: Path, checkpoint: Callable[[], None]) -> ModelIndex:
    index = ModelIndex()
    files = sorted(_python_files(module))
    if len(files) > LIMITS["files"]:
        index.complete = False
        return index
    total = 0
    for path in files:
        checkpoint()
        size = path.stat().st_size
        total += size
        if size > LIMITS["file_bytes"] or total > LIMITS["total_bytes"]:
            index.complete = False
            return index
        _scan_file(path, module, index)
    return index


def _python_files(module: Path) -> list[Path]:
    root = module.resolve()
    found = []
    for directory, _, names in os.walk(root):
        for name in names:
            path = Path(directory) / name
            if name.endswith(".py") and path.resolve().is_relative_to(root):
                found.append(path)
    return found


def _scan_file(path: Path, module: Path, index: ModelIndex) -> None:
    try:
        tree = ast.parse(path.read_bytes())
    except (OSError, SyntaxError, ValueError, RecursionError):
        index.complete = False
        return
    relative = path.relative_to(module.resolve()).as_posix()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            _scan_class(node, relative, index)


def _scan_class(node: ast.ClassDef, relative: str, index: ModelIndex) -> None:
    declared: dict[str, ast.expr] = {}
    for statement in node.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id in {"_name", "_inherit"}:
            declared[target.id] = value
    # With _name, _inherit lists parents; without it, _inherit names the extended models.
    names = _literal_names(declared["_name"] if "_name" in declared else declared.get("_inherit"))
    if names is None:
        index.complete = False
        return
    location = {
        "path": relative,
        "phase": "model",
        "line": node.lineno,
        "column": node.col_offset + 1,
    }
    for name in names:
        index.targets.setdefault(name.replace(".", "_"), location)


def _literal_names(value: ast.expr | None) -> list[str] | None:
    if value is None:
        return []
    try:
        literal = ast.literal_eval(value)
    except (ValueError, TypeError, SyntaxError, RecursionError):
        return None
    if isinstance(literal, str):
        return [literal]
    if isinstance(literal, (list, tuple)) and all(isinstance(item, str) for item in literal):
        return list(literal)
    return None
