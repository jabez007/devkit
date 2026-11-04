"""Changed-addon version rules through authorized commands and real local Git objects."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from mccann_hub.devkit.app import create_service

EFFECTS = ["read_fs", "write_fs", "execute_process"]


def git(project, *arguments):
    result = subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            *arguments,
        ],
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def manifest(module, version="19.0.1.0.0"):
    metadata = {"name": module.name, "depends": ["base"]}
    if version is not None:
        metadata["version"] = version
    (module / "__manifest__.py").write_text(repr(metadata))


@pytest.fixture
def version_project(odoo_project, monkeypatch):
    project, module = odoo_project
    monkeypatch.delenv("DEVKIT_BASE_COMMIT", raising=False)
    manifest(module)
    (module / "__init__.py").write_text("")
    git(project, "init", "--quiet", "--initial-branch", "main")
    git(project, "add", ".")
    git(project, "commit", "--quiet", "-m", "Baseline fixture")
    base = git(project, "rev-parse", "HEAD")
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    with policy.open("a") as stream:
        stream.write(
            '\n[commands."odoo.module.version.check"]\nproject='
            + json.dumps(str(project))
            + "\neffects="
            + json.dumps(EFFECTS)
            + '\nsurfaces=["python"]\n'
        )
    return project, module, base


def check(fixture, **arguments):
    project, _, base = fixture
    envelope = create_service(project).execute(
        "odoo.module.version.check", {"base_commit": base, **arguments}
    )
    assert json.loads(Path(envelope["evidence_path"]).read_text())["result"] == envelope["result"]
    return envelope["result"]


def change(module):
    (module / "delivery.py").write_text("DELIVERED = 4\n")


def test_changed_addon_without_version_bump_fails(version_project):
    _, module, _ = version_project
    change(module)
    result = check(version_project)
    assert (result["status"], result["reason"]) == ("failed", "VERSION_NOT_BUMPED"), result
    assert result["data"]["inspection_complete"] is True
    assert result["data"]["modules"][0]["module"] == "example"
    assert result["data"]["modules"][0]["before"] == result["data"]["modules"][0]["after"]


@pytest.mark.parametrize(
    "version,expected",
    [
        ("19.0.1.0.1", "success"),
        ("1.0.1", "success"),
        ("19.0.0.9.0", "failed"),
        ("1.0", "failed"),
        ("19.0", "failed"),
    ],
)
def test_version_must_increase_after_native_series_normalization(
    version_project, version, expected
):
    manifest(version_project[1], version)
    result = check(version_project)
    assert result["status"] == expected, result


def test_version_check_covers_all_changed_addons_despite_selected_runtime_module(version_project):
    project, first, _ = version_project
    second = project / "addons/second"
    second.mkdir()
    manifest(second)
    (second / "__init__.py").write_text("")
    git(project, "add", ".")
    git(project, "commit", "--quiet", "-m", "Second baseline addon")
    base = git(project, "rev-parse", "HEAD")
    (project / "devkit.toml").write_text('plugins=["odoo"]\n[options.odoo]\nmodule="example"\n')
    change(first)
    change(second)
    manifest(first, "19.0.1.0.1")
    result = check((project, first, base))
    assert result["status"] == "failed", result
    assert {item["module"] for item in result["data"]["modules"]} == {"example", "second"}


def test_new_addon_has_explicit_initial_version(version_project):
    project, _, _ = version_project
    added = project / "addons/new_addon"
    added.mkdir()
    manifest(added)
    result = check(version_project)
    assert result["status"] == "success", result
    assert result["data"]["modules"][0]["status"] == "new"


def test_missing_explicit_version_fails(version_project):
    manifest(version_project[1], None)
    result = check(version_project)
    assert result["status"] == "failed", result
    assert result["data"]["modules"][0]["after"] is None


def test_module_removal_does_not_silently_escape_version_coverage(version_project):
    shutil.rmtree(version_project[1])
    result = check(version_project)
    assert result["status"] == "failed", result
    assert result["data"]["modules"][0]["status"] == "removed"


def test_changes_outside_addons_do_not_require_an_addon_bump(version_project):
    (version_project[0] / "README.md").write_text("Documentation change\n")
    result = check(version_project)
    assert result["status"] == "success", result
    assert result["data"]["modules"] == []


def test_unknown_base_blocks_comparison(version_project):
    result = check(version_project, base_commit="0" * 40)
    assert (result["status"], result["reason"]) == ("blocked", "GIT_BASE_UNAVAILABLE"), result
    assert result["data"]["inspection_complete"] is False


def test_base_is_explicit_or_from_operator_environment(version_project, monkeypatch):
    project, _, base = version_project
    service = create_service(project)
    result = service.execute("odoo.module.version.check")["result"]
    assert (result["status"], result["reason"]) == ("blocked", "MISSING_BASE_COMMIT"), result
    monkeypatch.setenv("DEVKIT_BASE_COMMIT", base)
    assert service.execute("odoo.module.version.check")["result"]["status"] == "success"


def test_manifest_expressions_are_never_executed_by_version_check(version_project):
    _, module, _ = version_project
    marker = module / "must-not-exist"
    (module / "__manifest__.py").write_text(
        f"__import__('pathlib').Path({str(marker)!r}).touch() or {{'name':'Unsafe'}}"
    )
    result = check(version_project)
    assert result["status"] == "failed", result
    assert not marker.exists()


def test_base_blob_keeps_python_source_encoding(version_project):
    project, module, _ = version_project
    (module / "__manifest__.py").write_bytes(
        b"# coding: latin-1\n{'name':'Caf\xe9','version':'19.0.1.0.0'}"
    )
    git(project, "add", ".")
    git(project, "commit", "--quiet", "-m", "Encoded baseline metadata")
    base = git(project, "rev-parse", "HEAD")
    manifest(module, "19.0.1.0.1")
    assert check((project, module, base))["status"] == "success"


def test_symlinked_addon_layout_blocks_comparison(version_project):
    project, module, _ = version_project
    real = project / "real_addons"
    (project / "addons").rename(real)
    (project / "addons").symlink_to(real, target_is_directory=True)
    result = check(version_project)
    assert (result["status"], result["reason"]) == ("blocked", "UNSUPPORTED_GIT_LAYOUT"), result


def test_parent_traversal_is_refused(version_project):
    result = check(version_project, addons_paths=["../outside"])
    assert result["status"] != "success", result


def test_inherited_git_directory_cannot_redirect_comparison(version_project, tmp_path, monkeypatch):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    git(unrelated, "init", "--quiet")
    monkeypatch.setenv("GIT_DIR", str(unrelated / ".git"))
    change(version_project[1])
    manifest(version_project[1], "19.0.1.0.1")
    assert check(version_project)["status"] == "success"


def test_version_check_requires_explicit_process_and_write_effects(version_project):
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(policy.read_text().replace(json.dumps(EFFECTS), '["read_fs"]'))
    result = check(version_project)
    assert (result["status"], result["reason"]) == ("blocked", "DENIED"), result


@pytest.mark.parametrize("version,expected", [("1.0", "failed"), ("1.0.1", "success")])
def test_missing_base_version_uses_the_native_odoo_default(version_project, version, expected):
    project, module, _ = version_project
    manifest(module, None)
    git(project, "add", ".")
    git(project, "commit", "--quiet", "-m", "Baseline without explicit version")
    base = git(project, "rev-parse", "HEAD")
    manifest(module, version)
    assert check((project, module, base))["status"] == expected


@pytest.mark.parametrize("directory", ["custom addons", "custom\naddons"])
def test_changed_paths_preserve_literal_directory_names(version_project, directory):
    project, _, _ = version_project
    (project / "addons").rename(project / directory)
    git(project, "add", ".")
    git(project, "commit", "--quiet", "-m", "Literal addon path baseline")
    base = git(project, "rev-parse", "HEAD")
    module = project / directory / "example"
    change(module)
    result = check((project, module, base), addons_paths=[directory])
    assert result["status"] == "failed", result
    assert result["data"]["modules"][0]["path"] == directory + "/example"


def test_project_subdirectory_uses_correct_base_git_paths(version_project):
    project, _, _ = version_project
    application = project / "application"
    application.mkdir()
    (project / "addons").rename(application / "addons")
    (application / "devkit.toml").write_text('plugins=["odoo"]\n')
    git(project, "add", ".")
    git(project, "commit", "--quiet", "-m", "Project below Git root")
    base = git(project, "rev-parse", "HEAD")
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(policy.read_text().replace(str(project), str(application)))
    module = application / "addons/example"
    change(module)
    manifest(module, "19.0.1.0.1")
    assert check((application, module, base))["status"] == "success"


def test_linked_worktree_still_needs_its_own_exact_grant(version_project, tmp_path):
    project, _, base = version_project
    worktree = tmp_path / "worktree"
    git(project, "worktree", "add", "--detach", str(worktree), base)
    module = worktree / "addons/example"
    change(module)
    manifest(module, "19.0.1.0.1")
    fixture = worktree, module, base
    assert check(fixture)["reason"] == "DENIED"
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(policy.read_text().replace(str(project), str(worktree)))
    assert check(fixture)["status"] == "success"


def test_new_nested_repository_is_not_mistaken_for_a_fully_tracked_addon(version_project):
    project, _, _ = version_project
    nested = project / "addons/independent"
    nested.mkdir()
    manifest(nested)
    git(nested, "init", "--quiet")
    result = check(version_project)
    assert (result["status"], result["reason"]) == ("blocked", "UNSUPPORTED_GIT_LAYOUT"), result
