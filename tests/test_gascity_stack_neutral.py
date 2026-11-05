"""The shared pack and foundation must not name the first stack."""

from pathlib import Path


def test_shared_base_and_foundation_have_no_first_stack_names():
    root = Path(__file__).resolve().parents[1]
    directories = [
        root / "integrations/gascity/base",
        root / "packages/devkit/src",
    ]
    sources = {".py", ".toml", ".sh", ".md", ".json"}
    found = [
        str(path.relative_to(root))
        for directory in directories
        for path in directory.rglob("*")
        if path.suffix in sources and "odoo" in path.read_text().lower()
    ]
    assert found == [], found
