"""Installed-wheel acceptance fixture; never included in production packages."""

import os
from pathlib import Path

from devkit.contracts import CommandResult, CommandSpec, Context, JSONObject, Specialization

if marker := os.environ.get("DEVKIT_TEST_IMPORT_MARKER"):
    Path(marker).write_text("imported")


def inspect(context: Context, arguments: JSONObject) -> CommandResult:
    return CommandResult("success", "Sample command executed", {"value": 42})


def register() -> Specialization:
    return Specialization("sample", (CommandSpec("sample.inspect", "Inspect sample", inspect),))
