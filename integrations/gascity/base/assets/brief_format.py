"""Bounded behavior briefs, shared by native pack commands without Python plugins."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from native_state import BEAD_ID as TASK

MAX_BYTES = 100_000
REQUIRED = {"schema_version", "task_id", "problem", "acceptance_criteria", "approach", "scope"}
PATTERNS = {
    # Start once per path token; restarting at every hyphen makes long prose quadratic.
    "file_path": r"(?<![\w.-])(?:[.~]?[\\/])?(?:[\w.-]+[\\/])+[\w.*-]+",
    "dotted_name": r"\b[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+\b",
    "call": r"\b[A-Za-z_]\w*\(",
    "identifier": r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b",
    "command_flag": r"(?<!\w)--[a-z][a-z0-9-]*\b",
    "code": r"`",
    "source_file": (
        r"(?<![\w.-])[\w.-]+\.(?:py|xml|csv|js|jsx|ts|tsx|vue|json|toml|ya?ml|sql|sh|go|html|css|scss)\b"
    ),
}


class BriefError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise BriefError("INVALID_BRIEF")
        value[key] = item
    return value


def _read(path):
    # A model-written artifact must not hang the operator on a FIFO or substituted symlink.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise BriefError("INVALID_BRIEF")
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise BriefError("BRIEF_LIMIT")
    return content


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _list(value, *, required=False):
    return isinstance(value, list) and (bool(value) or not required) and all(map(_text, value))


def _valid(brief):
    if not isinstance(brief, dict) or not REQUIRED <= set(brief) <= REQUIRED | {"open_questions"}:
        return False
    if type(brief["schema_version"]) is not int or brief["schema_version"] != 1:
        return False
    task = brief["task_id"]
    if not isinstance(task, str) or TASK.fullmatch(task) is None:
        return False
    scope = brief["scope"]
    return (
        _text(brief["problem"])
        and _text(brief["approach"])
        and _list(brief["acceptance_criteria"], required=True)
        and isinstance(scope, dict)
        and set(scope) == {"in_scope", "out_of_scope"}
        and _list(scope["in_scope"], required=True)
        and _list(scope["out_of_scope"])
        and _list(brief.get("open_questions", []))
    )


def load(path, task=None):
    content = _read(Path(path))
    try:
        brief = json.loads(content.decode("utf-8"), object_pairs_hook=_object)
    except (ValueError, RecursionError) as error:
        raise BriefError("INVALID_BRIEF") from error
    if not _valid(brief):
        raise BriefError("INVALID_BRIEF")
    if task is not None and brief["task_id"] != task:
        raise BriefError("BRIEF_TASK_MISMATCH")
    return brief, hashlib.sha256(content).hexdigest(), content


def _sections(brief):
    yield "problem", brief["problem"]
    yield "approach", brief["approach"]
    for key in ("acceptance_criteria", "open_questions"):
        for index, text in enumerate(brief.get(key, [])):
            yield f"{key}[{index}]", text
    for key, values in brief["scope"].items():
        for index, text in enumerate(values):
            yield f"scope.{key}[{index}]", text


def findings(brief):
    result = []
    for section, text in _sections(brief):
        for kind, pattern in PATTERNS.items():
            for match in re.finditer(pattern, text):
                result.append(
                    {
                        "section": section,
                        "line": text.count("\n", 0, match.start()) + 1,
                        "kind": kind,
                    }
                )
                if len(result) == 100:
                    return result
    return result
