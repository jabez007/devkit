"""JSON validation with no external reference resolution."""

import json
from typing import Any

from jsonschema import Draft202012Validator
from mccann_hub.devkit.contracts import DevkitError, JSONObject


def check_schema(schema: JSONObject) -> None:
    """Limit v1 to self-contained schemas, including local fragment references."""
    dialect = "https://json-schema.org/draft/2020-12/schema"
    if schema.get("$schema", dialect) != dialect or schema.get("type") != "object":
        raise DevkitError("INVALID_SCHEMA", "Command schemas must describe Draft 2020-12 objects")
    Draft202012Validator.check_schema(schema)
    _check_references(schema)


def _check_references(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"$ref", "$dynamicRef"} and not str(item).startswith("#"):
                raise DevkitError("INVALID_SCHEMA", "External schema references are unsupported")
            if key == "$id":
                raise DevkitError("INVALID_SCHEMA", "Schema identifiers are unsupported in v1")
            _check_references(item)
    elif isinstance(value, list):
        for item in value:
            _check_references(item)


def validate(value: Any, schema: JSONObject) -> None:
    json.dumps(value, allow_nan=False)
    Draft202012Validator(schema).validate(value)


RESULT_SCHEMA: JSONObject = {
    "type": "object",
    "required": ["status", "summary", "data", "reason"],
    "additionalProperties": False,
    "properties": {
        "status": {"enum": ["success", "failed", "blocked", "error", "cancelled"]},
        "summary": {"type": "string", "maxLength": 4096},
        "data": {"type": "object"},
        "reason": {"type": ["string", "null"]},
    },
}
