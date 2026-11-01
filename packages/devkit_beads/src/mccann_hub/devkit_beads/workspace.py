"""Validate a normal Git checkout or its registered linked worktree.

Git and Beads own discovery. This module checks their identities agree; it does
not discover parent directories, initialize a ledger, or coordinate writers.
"""

import os
import stat
from collections.abc import Callable
from pathlib import Path

from mccann_hub.devkit.contracts import Status
from mccann_hub.devkit.processes import ProcessResult
from mccann_hub.devkit_beads.client import BeadsError

Invoke = Callable[[list[str]], ProcessResult]


def mismatch() -> BeadsError:
    return BeadsError(
        "blocked", "WORKSPACE_MISMATCH", "Git and Beads workspace identities do not agree"
    )


def canonical(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path:
        raise mismatch()
    return path


def git(invoke: Invoke, *arguments: str) -> str:
    result = invoke(["git", *arguments])
    if result.reason:
        status: Status = "cancelled" if result.reason == "CANCELLED" else "error"
        if result.reason == "MISSING_TOOL":
            status = "blocked"
        raise BeadsError(status, result.reason, "Git workspace inspection did not complete")
    if result.truncated:
        raise BeadsError("error", "OUTPUT_LIMIT", "Git workspace output exceeded the capture limit")
    if result.returncode:
        raise BeadsError(
            "blocked", "UNSUPPORTED_BEADS_WORKSPACE", "Select a registered Git checkout"
        )
    return result.stdout


def backlink(path: Path) -> Path:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise mismatch()
        data = stream.read(4097)
    if len(data) > 4096:
        raise mismatch()
    try:
        return canonical(data.decode("utf-8").rstrip("\n"))
    except UnicodeError as exc:
        raise mismatch() from exc


def registered(output: str, main: Path, root: Path) -> None:
    paths = []
    for entry in output.rstrip("\0").split("\0\0"):
        fields = entry.split("\0")
        if not fields[0].startswith("worktree ") or "bare" in fields:
            raise mismatch()
        path = canonical(fields[0].removeprefix("worktree "))
        if path in {main, root} and any(field.startswith("prunable") for field in fields):
            raise mismatch()
        paths.append(path)
    if not paths or paths[0] != main or paths.count(root) != 1:
        raise mismatch()


def ledger(main: Path, root: Path) -> Path:
    for directory in {main / ".beads", root / ".beads"}:
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise BeadsError("blocked", "BEADS_NOT_INITIALIZED", "Use a real .beads directory")
        if (directory / "redirect").exists() or (directory / "redirect").is_symlink():
            raise BeadsError(
                "blocked", "UNSUPPORTED_BEADS_WORKSPACE", "External Beads redirects are unsupported"
            )
    directory = main / ".beads"
    if not directory.is_dir():
        raise BeadsError(
            "blocked", "BEADS_NOT_INITIALIZED", "Initialize Beads in the main checkout first"
        )
    return canonical(str(directory))


def resolve(root: Path, invoke: Invoke) -> Path:
    """Return the main checkout only after native topology and backlinks agree."""
    marker = root / ".git"
    if marker.is_symlink():
        raise mismatch()
    # Preserve the ordinary checkout's missing-workspace diagnostic before tools run.
    if marker.is_dir():
        ledger(root, root)
    output = git(
        invoke,
        "rev-parse",
        "--path-format=absolute",
        "--show-toplevel",
        "--git-common-dir",
        "--absolute-git-dir",
        "--is-bare-repository",
    ).splitlines()
    if len(output) != 4 or output[3] != "false":
        raise mismatch()
    selected, common, administrative = map(canonical, output[:3])
    main = common.parent
    if selected != root or common.name != ".git" or not common.is_dir():
        raise mismatch()
    registered(git(invoke, "worktree", "list", "--porcelain", "-z"), main, root)
    if root == main:
        if administrative != common or not marker.is_dir():
            raise mismatch()
    elif (
        administrative.parent != common / "worktrees"
        or backlink(administrative / "gitdir") != marker
    ):
        raise mismatch()
    ledger(main, root)
    return main
