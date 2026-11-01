"""Bounded README verification through the public specialization contract."""

import os
import stat

from devkit.contracts import (
    CheckSpec,
    CommandResult,
    CommandSpec,
    Context,
    JSONObject,
    Specialization,
)

LIMIT = 65_536


def inspect_readme(context: Context, arguments: JSONObject) -> CommandResult:
    path = context.project_root / arguments.get("filename", "README.md")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return CommandResult(
                    "blocked", f"{path.name} must be a regular file", reason="UNSAFE_PATH"
                )
            content = stream.read(LIMIT + 1)
        if len(content) > LIMIT:
            return CommandResult("blocked", f"{path.name} exceeds 64 KiB", reason="READ_LIMIT")
        lines = content.decode("utf-8").splitlines()
    except (OSError, UnicodeError):
        return CommandResult(
            "blocked", f"Provide a readable UTF-8 {path.name}", reason="README_UNAVAILABLE"
        )
    trailing = [number for number, line in enumerate(lines, 1) if line.rstrip() != line]
    return CommandResult(
        "failed" if trailing else "success",
        "Remove trailing whitespace on the listed README lines"
        if trailing
        else "README whitespace checked",
        {"lines": len(lines), "trailing_whitespace_lines": trailing},
        "TRAILING_WHITESPACE" if trailing else None,
    )


def register() -> Specialization:
    command = CommandSpec(
        "example.readme",
        "Check bounded README text for trailing whitespace",
        inspect_readme,
        effects=frozenset({"read_fs"}),
        surfaces=frozenset({"cli", "python", "mcp"}),
        input_schema={
            "type": "object",
            "properties": {"filename": {"enum": ["README.md", "README.rst"]}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["lines", "trailing_whitespace_lines"],
            "properties": {
                "lines": {"type": "integer", "minimum": 0},
                "trailing_whitespace_lines": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                },
            },
            "additionalProperties": False,
        },
    )
    return Specialization("example", (command,), checks=(CheckSpec("example.readme", command.id),))
