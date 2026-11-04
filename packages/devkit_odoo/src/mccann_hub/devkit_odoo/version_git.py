"""Local Git objects and changed paths with supervised, bounded byte capture."""

import os
import re
import tempfile
from pathlib import Path, PurePosixPath

from mccann_hub.devkit.contracts import Context, DevkitError
from mccann_hub.devkit.processes import run_process


class Git:
    def __init__(self, context: Context, base: str) -> None:
        self.context, self.base = context, base
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.environment.update(
            GIT_TERMINAL_PROMPT="0",
            GIT_OPTIONAL_LOCKS="0",
            GIT_ALLOW_PROTOCOL="",
            GIT_NO_LAZY_FETCH="1",
        )
        self.entries: dict[str, tuple[str, str, str] | None] = {}
        self.read(["cat-file", "-e", base + "^{commit}"])
        self.prefix = self.read(["rev-parse", "--show-prefix"]).decode().removesuffix("\n")

    def read(self, arguments: list[str], limit: int = 1_048_576) -> bytes:
        with tempfile.TemporaryFile() as output:
            process = run_process(
                [
                    "git",
                    "--literal-pathspecs",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    *arguments,
                ],
                self.context,
                environment=self.environment,
                stdout_file=output,
            )
            if process.reason:
                raise DevkitError(process.reason, "Git inspection did not complete")
            if process.returncode:
                raise DevkitError(
                    "GIT_BASE_UNAVAILABLE", "Cannot inspect the selected local Git base"
                )
            output.seek(0)
            content = output.read(limit + 1)
        if process.truncated or len(content) > limit:
            raise DevkitError("GIT_OUTPUT_LIMIT", "Git inspection output exceeds its capture limit")
        return content

    def changed(self) -> list[Path]:
        raw = self.read(
            [
                "diff",
                "--relative",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--name-only",
                "-z",
                self.base,
                "--",
            ]
        )
        raw += self.read(["ls-files", "--others", "--exclude-standard", "-z"])
        try:
            paths = [Path(part.decode("utf-8")) for part in raw.split(b"\0") if part]
        except UnicodeError as error:
            raise DevkitError("UNSUPPORTED_GIT_LAYOUT", "Changed paths must use UTF-8") from error
        if len(paths) > 10000 or any(path.is_absolute() or ".." in path.parts for path in paths):
            raise DevkitError("GIT_OUTPUT_LIMIT", "Narrow the changed-addon inventory")
        return paths

    def _entry(self, path: str) -> tuple[str, str, str] | None:
        if path in self.entries:
            return self.entries[path]
        raw = self.read(["ls-tree", "-z", "--full-tree", self.base, "--", path])
        if not raw:
            self.entries[path] = None
            return None
        records = raw.rstrip(b"\0").split(b"\0")
        if len(records) != 1:
            raise DevkitError("UNSUPPORTED_GIT_LAYOUT", "Expected one exact Git tree entry")
        header, _, name = records[0].partition(b"\t")
        parts = header.decode("ascii").split()
        if (
            len(parts) != 3
            or name.decode("utf-8") != path
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", parts[2])
        ):
            raise DevkitError("UNSUPPORTED_GIT_LAYOUT", "Cannot identify the base manifest object")
        entry = parts[0], parts[1], parts[2]
        self.entries[path] = entry
        return entry

    def _supported_ancestor(self, path: PurePosixPath) -> None:
        while path != PurePosixPath("."):
            entry = self._entry(path.as_posix())
            if entry is not None:
                if entry[0] in {"120000", "160000"}:
                    raise DevkitError(
                        "UNSUPPORTED_GIT_LAYOUT", "Validate linked addons in their own repository"
                    )
                return
            path = path.parent

    def manifest(self, module: Path) -> bytes | None:
        path = self.prefix + (module / "__manifest__.py").as_posix()
        entry = self._entry(path)
        if entry is None:
            self._supported_ancestor(PurePosixPath(path).parent)
            return None
        if entry[0] not in {"100644", "100755"} or entry[1] != "blob":
            raise DevkitError(
                "UNSUPPORTED_GIT_LAYOUT", "Base manifests must be ordinary tracked files"
            )
        return self.read(["cat-file", "blob", entry[2]], 262_144)
