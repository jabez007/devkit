"""Bounded local reads shared by the Odoo data-file inspectors."""

from collections.abc import Callable
from pathlib import Path

from mccann_hub.devkit.contracts import DevkitError


class FileBudget:
    def __init__(self, kind: str, limits: dict[str, int], checkpoint: Callable[[], None]) -> None:
        self.kind = kind
        self.limits = limits
        self.checkpoint = checkpoint
        self.files = 0
        self.bytes = 0

    def read(self, path: Path) -> bytes:
        self.checkpoint()
        self.files += 1
        if self.files > self.limits["files"] or self.bytes >= self.limits["total_bytes"]:
            raise DevkitError(
                f"{self.kind}_LIMIT",
                f"{self.kind} invocation budget exhausted; select fewer modules",
            )
        with path.open("rb") as stream:
            content = stream.read(self.limits["file_bytes"] + 1)
        self.bytes += len(content)
        if len(content) > self.limits["file_bytes"] or self.bytes > self.limits["total_bytes"]:
            raise DevkitError(
                f"{self.kind}_LIMIT", f"{self.kind} byte limit exceeded; narrow the inspection"
            )
        return content
