"""Independent specialization source: copy into a renamed plugin template."""

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
    path = context.project_root / "README.md"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return CommandResult(
                    "blocked", "README.md must be a regular file", reason="UNSAFE_PATH"
                )
            content = stream.read(LIMIT + 1)
        if len(content) > LIMIT:
            return CommandResult("blocked", "README.md exceeds 64 KiB", reason="READ_LIMIT")
        lines = content.decode("utf-8").splitlines()
    except (OSError, UnicodeError):
        return CommandResult(
            "blocked", "Provide a readable UTF-8 README.md", reason="README_UNAVAILABLE"
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
        "textcheck.readme",
        "Check bounded README text for trailing whitespace",
        inspect_readme,
        effects=frozenset({"read_fs"}),
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
    return Specialization(
        "textcheck", (command,), checks=(CheckSpec("textcheck.readme", command.id),)
    )
