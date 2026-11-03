"""Load a complete rule set; extensions can only add denials."""

import json
import re
from pathlib import Path

REQUIRED = {
    "no-force-push",
    "no-pr-publish",
    "no-protected-push",
    "no-remote-delete",
    "no-background",
    "no-credential-access",
    "literal-shell",
}
LIST_FIELDS = {"no-protected-push": "branches", "no-credential-access": "paths"}


class Refusal(ValueError):
    """A public rule identifier and static explanation, never tool input or secrets."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal("guard-config: duplicate JSON key")
        result[key] = value
    return result


def _read(path):
    with path.open("rb") as stream:
        content = stream.read(65_537)
    if len(content) > 65_536:
        raise Refusal("guard-config: rules exceed 64 KiB")
    config = json.loads(content, object_pairs_hook=_object)
    if not isinstance(config, dict) or set(config) != {"version", "rules"}:
        raise Refusal("guard-config: expected version and rules")
    if type(config["version"]) is not int or config["version"] != 1:
        raise Refusal("guard-config: unsupported rule version")
    if not isinstance(config["rules"], dict):
        raise Refusal("guard-config: rules must be an object")
    return config["rules"]


def _strings(value):
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def _base_rule(name, value, base):
    if name not in LIST_FIELDS:
        if value != base:
            raise Refusal(f"{name}: base rule cannot be changed")
        return
    field = LIST_FIELDS[name]
    if not isinstance(value, dict) or set(value) != {field} or not _strings(value[field]):
        raise Refusal(f"{name}: required base values are missing")
    if not set(base[field]).issubset(value[field]):
        raise Refusal(f"{name}: base values cannot be removed")


def load(path=None):
    base = _read(Path(__file__).with_name("base-rules.json"))
    if set(base) != REQUIRED:
        raise Refusal("guard-config: bundled base rules are incomplete")
    rules = _read(path) if path else base
    for name in sorted(REQUIRED):
        if name not in rules:
            raise Refusal(f"{name}: required base rule is missing")
        _base_rule(name, rules[name], base[name])
    for name, value in rules.items():
        if name in REQUIRED:
            continue
        if not re.fullmatch(r"[a-z][a-z0-9.-]{0,63}", name):
            raise Refusal("guard-config: invalid extension rule identifier")
        if not isinstance(value, dict) or set(value) != {"command_prefix"}:
            raise Refusal(f"{name}: extension must declare command_prefix")
        if not _strings(value["command_prefix"]):
            raise Refusal(f"{name}: command_prefix must contain literal words")
    return rules
