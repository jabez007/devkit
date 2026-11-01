"""Verify an operator-pinned wheel against its installed payload without importing it."""

import hashlib
import io
import json
from importlib.metadata import Distribution
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile, ZipInfo

from mccann_hub.devkit.contracts import DevkitError, JSONObject

MAX_WHEEL = 64 * 1024 * 1024
MAX_PAYLOAD = 256 * 1024 * 1024


def verify_wheel(distribution: Distribution | None, pin: JSONObject) -> str:
    """Fail closed on editable installs and unsupported wheel relocation schemes."""
    try:
        if distribution is None:
            raise ValueError("Missing installed metadata")
        origin = json.loads(distribution.read_text("direct_url.json") or "{}")
        if origin.get("dir_info", {}).get("editable"):
            raise ValueError("Editable installations cannot be attested")
        wheel = Path(pin["wheel"])
        if not wheel.is_absolute() or wheel.stat().st_size > MAX_WHEEL:
            raise ValueError("Expected a bounded absolute wheel path")
        with wheel.open("rb") as stream:
            payload = stream.read(MAX_WHEEL + 1)
        digest = hashlib.sha256(payload).hexdigest()
        if len(payload) > MAX_WHEEL or digest != pin["sha256"]:
            raise ValueError("Wheel hash mismatch")
        with ZipFile(io.BytesIO(payload)) as archive:
            _verify_payload(distribution, archive)
        return digest
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        BadZipFile,
        RuntimeError,
    ) as exc:
        raise DevkitError(
            "ARTIFACT_MISMATCH", "Plugin wheel or installed payload failed verification"
        ) from exc


def _members(archive: ZipFile) -> list[ZipInfo]:
    entries = [entry for entry in archive.infolist() if not entry.is_dir()]
    names = {entry.filename for entry in entries}
    if len(entries) > 10000 or len(entries) != len(names):
        raise ValueError("Invalid wheel inventory")
    if sum(entry.file_size for entry in entries) > MAX_PAYLOAD:
        raise ValueError("Wheel payload exceeds size limit")
    metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
    if len(metadata) != 1:
        raise ValueError("Expected one distribution")
    return entries


def _payload_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or str(path) != name or "\\" in name:
        raise ValueError("Unsafe wheel path")
    if path.parts[0].endswith(".data") or path.suffix in {".pth", ".pyc"}:
        raise ValueError("Relocated, editable, and bytecode payloads are unsupported")
    return path


def _verify_payload(distribution: Distribution, archive: ZipFile) -> None:
    root = Path(str(distribution.locate_file(""))).resolve()
    for entry in _members(archive):
        relative = _payload_path(entry.filename)
        path = root.joinpath(*relative.parts)
        if any(part.is_symlink() for part in (path, *path.parents) if part != root):
            raise ValueError("Installed payload contains symlinks")
        if entry.filename.endswith(".dist-info/RECORD"):
            continue  # Installers rewrite RECORD and generate wrappers/cache files.
        if path.stat().st_size != entry.file_size:
            raise ValueError("Installed size mismatch")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").digest()
        if actual != hashlib.sha256(archive.read(entry)).digest():
            raise ValueError("Installed content mismatch")
    # Bind the approved metadata to this discovered distribution, not a sibling install.
    name = next(
        entry.filename
        for entry in _members(archive)
        if entry.filename.endswith(".dist-info/METADATA")
    )
    if archive.read(name).decode() != distribution.read_text("METADATA"):
        raise ValueError("Distribution metadata mismatch")
