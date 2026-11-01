"""Validate shipped metadata and rebuild distribution payloads from their sdists."""

import email
import subprocess
import tarfile
from zipfile import ZipFile

NAMES = (
    "mccann_hub.devkit",
    "mccann_hub.devkit_go",
    "mccann_hub.devkit_odoo",
    "mccann_hub.devkit_beads",
    "mccann_hub.devkit_mcp",
    "mccann_hub.devkit_example",
)


def payload(wheel):
    with ZipFile(wheel) as archive:
        return {
            name: archive.read(name) for name in archive.namelist() if not name.endswith("/RECORD")
        }


def check(wheels, root):
    for name in NAMES:
        wheel = next(wheels.glob(f"{name.replace('.', '_')}-*.whl"))
        contents = payload(wheel)
        metadata = email.message_from_bytes(
            next(data for path, data in contents.items() if path.endswith("/METADATA"))
        )
        assert metadata["Summary"] and metadata["Requires-Python"] == ">=3.12"
        assert metadata["Description-Content-Type"] == "text/markdown"
        assert metadata["Name"] == name.replace(".", "-").replace("_", "-")
        assert metadata["License-Expression"] == "GPL-3.0-or-later"
        assert "LICENSE" in metadata.get_all("License-File", [])
        license_text = next(data for path, data in contents.items() if path.endswith("/LICENSE"))
        assert b"GNU GENERAL PUBLIC LICENSE" in license_text
        assert "mccann_hub/__init__.py" not in contents
        assert all(not path.startswith("devkit/") for path in contents)
        assert "# " in metadata.get_payload()
        if name == "mccann_hub.devkit":
            assert "mccann_hub/devkit/py.typed" in contents
            assert all("pytest" not in value for value in metadata.get_all("Requires-Dist", []))
        if name not in {"mccann_hub.devkit", "mccann_hub.devkit_mcp"}:
            entries = next(
                data for path, data in contents.items() if path.endswith("/entry_points.txt")
            )
            assert b"mccann_hub.devkit.specializations.v1" in entries
        destination = root / name
        with tarfile.open(next(wheels.glob(f"{name.replace('.', '_')}-*.tar.gz"))) as archive:
            names = archive.getnames()
            assert any(path.endswith("/README.md") for path in names)
            assert any(path.endswith("/LICENSE") for path in names)
            assert not any("/.venv/" in path or "/.git/" in path for path in names)
            archive.extractall(destination, filter="data")
        source = next(destination.iterdir())
        output = destination / "rebuilt"
        subprocess.run(["uv", "build", "--wheel", "--out-dir", str(output)], cwd=source, check=True)
        assert payload(next(output.glob("*.whl"))) == contents, (
            f"sdist changed wheel payload: {name}"
        )
    print("PASS: six distribution metadata inventories and independent sdist-to-wheel rebuilds")
