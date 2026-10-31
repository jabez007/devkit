"""Exercise the public invocation seam using a real, controllable CLI executable."""

import json
import os
import sys

import pytest

SCOPE = "36f6082f-9554-498f-a8f8-4b826083371f"
REF = f"beads:{SCOPE}:demo-1"
FAKE = """
import json, os, sys, time
from pathlib import Path
root = Path.cwd()
settings = json.loads((root / "fake.json").read_text())
with (root / "calls.jsonl").open("a") as out:
    out.write(json.dumps({"argv":sys.argv[1:], "env":dict(os.environ)}) + "\\n")
assert sys.argv[1:4] == ["--readonly", "--sandbox", "--json"]
assert os.environ["BD_DISABLE_METRICS"] == "1"
assert os.environ["BEADS_DIR"] == str(root / ".beads")
assert "TEST_SECRET" not in os.environ
command = sys.argv[4]
mode = settings.get("mode")
if mode == "sleep":
    time.sleep(30)
if mode == "unavailable":
    sys.exit(1)
if mode == "malformed":
    print("not json"); sys.exit()
if mode == "oversized":
    print("x" * 300000); sys.exit()
item = {"id":"demo-1", "title":"Check project", "status":"open", "priority":2, "issue_type":"task"}
if command == "version":
    result = {"version":settings.get("version", "1.3.2")}
elif command == "context":
    result = {"schema_version":1,"backend":"dolt","dolt_mode":"embedded","bd_version":"1.3.2",
              "beads_dir":str(root / ".beads"),"repo_root":str(root),
              "is_redirected":False,"is_worktree":False,"project_id":settings["scope"]}
    result.update(settings.get("context", {}))
elif command == "show":
    result = settings.get("show", [item])
elif command == "dep":
    result = [{**item, "id":"demo-2", "dependency_type":"blocks"}]
else:
    result = settings.get("ready", [item])
print(json.dumps(result))
"""


@pytest.fixture
def beads_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / ".beads").mkdir(parents=True)
    (project / "devkit.toml").write_text('plugins=["beads"]')
    (project / "fake.json").write_text(json.dumps({"scope": SCOPE}))
    binary = tmp_path / "bin/bd"
    binary.parent.mkdir()
    binary.write_text(f"#!{sys.executable}\n" + FAKE)
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("TEST_SECRET", "must-not-inherit")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    from devkit_beads import register

    policy = tmp_path / "config/devkit/policy.toml"
    policy.parent.mkdir(parents=True)
    text = '[trusted_plugins]\ndevkit-beads="0.1.0"\n'
    for spec in register().commands:
        text += f'[commands."{spec.id}"]\nproject={json.dumps(str(project))}\n'
        text += f'effects={json.dumps(sorted(spec.effects))}\nsurfaces=["cli","python","mcp"]\n'
    policy.write_text(text)
    policy.chmod(0o600)
    return project


def configure(project, **settings):
    (project / "fake.json").write_text(json.dumps({"scope": SCOPE, **settings}))
