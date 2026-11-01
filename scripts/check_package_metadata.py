"""Validate shipped metadata and rebuild distribution payloads from their sdists."""

import email
import subprocess
import tarfile
from zipfile import ZipFile

NAMES = ("devkit", "devkit_go", "devkit_odoo", "devkit_beads", "devkit_mcp", "devkit_example")


def payload(wheel):
    with ZipFile(wheel) as archive:
        return {
            name: archive.read(name) for name in archive.namelist() if not name.endswith("/RECORD")
        }


def check(wheels, root):
    for name in NAMES:
        wheel = next(wheels.glob(f"{name}-*.whl"))
        contents = payload(wheel)
        metadata = email.message_from_bytes(
            next(data for path, data in contents.items() if path.endswith("/METADATA"))
        )
        assert metadata["Summary"] and metadata["Requires-Python"] == ">=3.12"
        assert metadata["Description-Content-Type"] == "text/markdown"
        assert "# " in metadata.get_payload()
        if name == "devkit":
            assert "devkit/py.typed" in contents
            assert all("pytest" not in value for value in metadata.get_all("Requires-Dist", []))
        if name not in {"devkit", "devkit_mcp"}:
            entries = next(
                data for path, data in contents.items() if path.endswith("/entry_points.txt")
            )
            assert b"devkit.specializations.v1" in entries
        destination = root / name
        with tarfile.open(next(wheels.glob(f"{name}-*.tar.gz"))) as archive:
            names = archive.getnames()
            assert any(path.endswith("/README.md") for path in names)
            assert not any("/.venv/" in path or "/.git/" in path for path in names)
            archive.extractall(destination, filter="data")
        source = next(destination.iterdir())
        output = destination / "rebuilt"
        subprocess.run(["uv", "build", "--wheel", "--out-dir", str(output)], cwd=source, check=True)
        assert payload(next(output.glob("*.whl"))) == contents, (
            f"sdist changed wheel payload: {name}"
        )
    print("PASS: six distribution metadata inventories and independent sdist-to-wheel rebuilds")
