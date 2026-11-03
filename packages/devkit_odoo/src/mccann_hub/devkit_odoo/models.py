"""Model names in reachable addon Python sources, read with ast and never imported.

Odoo creates ``<module>.model_<name>`` and ``<module>.field_<name>__<field>`` IDs when
it registers the models a module defines or extends. Those IDs exist before any data
file loads, so data files can reference them without defining them. A field ID exists
for each field the module declares, which may include fields from parent models and
mixins that this scan cannot see.
"""

import ast
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mccann_hub.devkit.contracts import JSONObject
from mccann_hub.devkit_odoo.python_inspection import PythonImports


@dataclass
class ModelIndex:
    """Generated-ID targets; ``complete`` is false when imports or model names are uncertain.

    Keys are model names with dots replaced by underscores, as in the generated IDs.
    """

    targets: dict[str, JSONObject] = field(default_factory=dict)
    fields: dict[str, dict[str, JSONObject]] = field(default_factory=dict)
    complete: bool = True

    def target(self, local_id: str) -> JSONObject | None:
        """Where the ID's model, or its field declared by a literal assignment, is defined."""
        if local_id.startswith("model_"):
            return self.targets.get(local_id.removeprefix("model_"))
        for model, name in _field_parts(local_id):
            if location := self.fields.get(model, {}).get(name):
                return location
        return None

    def may_generate(self, local_id: str) -> bool:
        """A field ID on a model this module declares, for a field the scan did not find."""
        models = (model for model, _ in _field_parts(local_id))
        return any(model in self.targets for model in models) and self.target(local_id) is None


def _field_parts(local_id: str) -> list[tuple[str, str]]:
    """Every (model, field) split; model and field names may themselves contain ``__``."""
    if not local_id.startswith("field_"):
        return []
    rest = local_id.removeprefix("field_")
    starts = [index for index in range(len(rest)) if rest.startswith("__", index)]
    return [(rest[:index], rest[index + 2 :]) for index in starts]


def scan_models(module: Path, checkpoint: Callable[[], None]) -> ModelIndex:
    index = ModelIndex()
    imports = PythonImports(module, checkpoint)
    for relative, tree in imports.sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                _scan_class(node, relative, index)
    index.complete &= imports.complete
    return index


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
    fields = {
        statement.targets[0].id: _location(relative, statement)
        for statement in node.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and _is_field(statement.value)
    }
    for name in names:
        key = name.replace(".", "_")
        index.targets.setdefault(key, _location(relative, node))
        for field_name, location in fields.items():
            index.fields.setdefault(key, {}).setdefault(field_name, location)


def _is_field(value: ast.expr) -> bool:
    """``fields.Char(...)`` and the like, the form Odoo addons use to declare fields."""
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "fields"
    )


def _location(relative: str, node: ast.stmt) -> JSONObject:
    return {"path": relative, "phase": "model", "line": node.lineno, "column": node.col_offset + 1}


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
