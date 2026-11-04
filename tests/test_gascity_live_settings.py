"""Reusing a task city repairs managed settings and preserves unrelated configuration."""

import json
import shlex
import tomllib
from types import SimpleNamespace

from tests.gascity_odoo_live import _migrate_guard, _workspace_environment


def test_repeated_workspace_environment_updates_one_table_and_preserves_other_values(tmp_path):
    path = tmp_path / "city.toml"
    path.write_text(
        '[workspace]\n[workspace.env]\nUSER_SETTING="kept"\nIMAGE="old"\n'
        '[beads]\nnative_transport="off"\n'
    )
    _workspace_environment(path, {"IMAGE": "new", "EXTRA": "one\ntwo"})
    _workspace_environment(path, {"IMAGE": "latest"})
    value = tomllib.loads(path.read_text())
    assert value["workspace"]["env"] == dict(USER_SETTING="kept", IMAGE="latest", EXTRA="one\ntwo")
    assert value["beads"]["native_transport"] == "off"
    assert path.read_text().count("[workspace.env]") == 1


def test_pack_path_change_removes_only_the_previous_managed_guard_entry(tmp_path):
    city = tmp_path / "city"
    worktree = city / "worktrees/task"
    (worktree / ".claude").mkdir(parents=True)
    (city / "city.toml").write_text(
        '[workspace.env]\nDEVKIT_PACK_BASE="/old/integrations/gascity/base"\n'
    )
    command = shlex.join(
        [
            "python",
            "/old/integrations/unattended/guard.py",
            "--rules",
            str(worktree / ".claude/devkit-unattended-rules.json"),
        ]
    )
    old = {"matcher": "*", "hooks": [{"type": "command", "command": command, "timeout": 10}]}
    custom = {"matcher": "Bash", "hooks": [{"type": "command", "command": "custom-check"}]}
    settings = worktree / ".claude/settings.json"
    settings.write_text(json.dumps(dict(hooks=dict(PreToolUse=[old, custom]), model="kept")))
    _migrate_guard(SimpleNamespace(city=city, worktree=worktree))
    actual = json.loads(settings.read_text())
    assert actual["hooks"]["PreToolUse"] == [custom]
    assert actual["model"] == "kept"
