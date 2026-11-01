import hashlib
import sys
from importlib.metadata import Distribution
from zipfile import ZipFile

import pytest
from mccann_hub.devkit.contracts import DevkitError
from mccann_hub.devkit.discovery import Candidate, activate
from mccann_hub.devkit.policy import Policy, load_policy


@pytest.fixture
def installed_plugin(tmp_path, monkeypatch):
    site = tmp_path / "site"
    metadata = "artifact_sample-1.0.dist-info"
    payload = {
        "artifact_sample/__init__.py": (
            "from pathlib import Path\n"
            f"Path({str(tmp_path / 'imported')!r}).touch()\n"
            "from mccann_hub.devkit.contracts import Specialization\n"
            "def register(): return Specialization('artifact', ())\n"
        ),
        f"{metadata}/METADATA": "Metadata-Version: 2.1\nName: artifact-sample\nVersion: 1.0\n",
        f"{metadata}/WHEEL": "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{metadata}/entry_points.txt": (
            "[mccann_hub.devkit.specializations.v1]\nartifact = artifact_sample:register\n"
        ),
        f"{metadata}/RECORD": "",
    }
    wheel = tmp_path / "artifact_sample-1.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        for name, content in payload.items():
            archive.writestr(name, content)
            path = site / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    dist = Distribution.at(site / metadata)
    entry = Candidate("artifact", "artifact-sample", "1.0", next(iter(dist.entry_points)))
    pin = {
        "version": "1.0",
        "wheel": str(wheel),
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.delitem(sys.modules, "artifact_sample", raising=False)
    return entry, pin, site, tmp_path / "imported"


def test_approved_wheel_loads_and_records_identity(installed_plugin):
    entry, pin, _, marker = installed_plugin
    result = activate(("artifact",), Policy({"artifact-sample": pin}), (entry,))
    assert marker.exists()
    assert result[0][1].artifact_sha256 == pin["sha256"]


@pytest.mark.parametrize("change", ["installed", "wheel", "missing", "editable", "symlink"])
def test_replaced_same_version_payload_is_blocked_before_import(installed_plugin, change):
    entry, pin, site, marker = installed_plugin
    source = site / "artifact_sample/__init__.py"
    if change == "installed":
        source.write_text("raise RuntimeError('replacement')")
    elif change == "wheel":
        with ZipFile(pin["wheel"], "a") as archive:
            archive.writestr("extra.py", "replacement")
    elif change == "missing":
        source.unlink()
    elif change == "editable":
        (site / "artifact_sample-1.0.dist-info/direct_url.json").write_text(
            '{"dir_info":{"editable":true},"url":"file:///example"}'
        )
    else:
        original = source.read_bytes()
        source.unlink()
        target = site.parent / "outside.py"
        target.write_bytes(original)
        source.symlink_to(target)
    with pytest.raises(DevkitError) as caught:
        activate(("artifact",), Policy({"artifact-sample": pin}), (entry,))
    assert caught.value.reason == "ARTIFACT_MISMATCH"
    assert not marker.exists()


def test_structured_pin_policy_and_legacy_trust(tmp_path, monkeypatch):
    config = tmp_path / "config/devkit"
    config.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))
    (config / "policy.toml").write_text(
        '[trusted_plugins]\nlegacy="1.0"\n'
        '[trusted_plugins.pinned]\nversion="1.0"\nwheel="/trusted/plugin.whl"\n'
        f'sha256="{"a" * 64}"\n'
    )
    (config / "policy.toml").chmod(0o600)
    policy = load_policy(tmp_path / "project")
    assert policy.trusts("legacy", "1.0")
    assert not policy.trusts("pinned", "1.0")
    assert policy.trusts("pinned", "1.0", "a" * 64)
