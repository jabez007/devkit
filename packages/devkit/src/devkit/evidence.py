"""Atomic local evidence, minimal source provenance, and output redaction."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from devkit.contracts import JSONObject

SECRET_KEY = re.compile(r"secret|token|password|api[_-]?key|credential", re.I)
TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SECRET_KEY.search(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = TOKEN.sub("[REDACTED]", value)
        for key, secret in os.environ.items():
            if SECRET_KEY.search(key) and len(secret) >= 4:
                value = value.replace(secret, "[REDACTED]")
        return value
    return value


def source_identity(root: Path) -> JSONObject:
    result: JSONObject = {"revision": None, "dirty": None}
    try:
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout
        result.update(revision=revision, dirty=bool(dirty))
    except (OSError, subprocess.SubprocessError):
        pass
    return result


def write_bundle(state: Path, envelope: JSONObject) -> Path:
    """Unique run directories prevent overwrites and cross-run artifact references."""
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    run = state / "runs" / str(envelope["run_id"])
    run.mkdir(parents=True, mode=0o700)
    identity = hashlib.sha256(envelope["project_root"].encode()).hexdigest()
    envelope["project_id"] = identity
    path = run / "result.json"
    temporary = run / ".result.tmp"
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(envelope, stream, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return path
