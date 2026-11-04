"""Prepare reviewed guard settings and native Docker bindings without launching a session."""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from launch import _json, configuration

BASE = Path(__file__).resolve().parents[1]
GUARD = Path(__file__).resolve().parents[3] / "unattended"
REQUIRED = {
    "session",
    "claude",
    "credentials",
    "config_dir",
    "runtime",
    "image",
    "user",
    "network",
    "packs",
    "readonly",
    "writable",
    "default_branch",
    "protected_branches",
}


def _strings(value, maximum=64):
    return (
        isinstance(value, list)
        and len(value) <= maximum
        and all(isinstance(item, str) and item and len(item) <= 4096 for item in value)
    )


def _absolute(value):
    if not isinstance(value, str) or not value or any(c.isspace() or c == "," for c in value):
        raise ValueError("Native runtime paths cannot contain whitespace or commas")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Native runtime paths must be absolute")
    return path


def _path(value):
    return _absolute(value).resolve(strict=True)


def _deployment(path):
    config = _json(path)
    if not isinstance(config, dict) or not REQUIRED <= set(config) <= REQUIRED | {"stack_rules"}:
        raise ValueError("Expected the documented deployment configuration")
    for key in ("packs", "readonly", "writable", "protected_branches"):
        if not _strings(config[key]):
            raise ValueError("Expected bounded path and branch lists")
    default = config["default_branch"]
    if not isinstance(default, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", default):
        raise ValueError("An operator-selected default branch is required")
    for key in ("image", "network"):
        if not isinstance(config[key], str) or not re.fullmatch(r"[A-Za-z0-9_./:@-]+", config[key]):
            raise ValueError("Invalid native Docker setting")
    if not isinstance(config["user"], str) or not re.fullmatch(r"[0-9]+:[0-9]+", config["user"]):
        raise ValueError("An explicit container UID and GID are required")
    return config


def _mount_path(value):
    path = _path(value)
    home = Path.home().resolve()
    socket = Path("/var/run/docker.sock").resolve()
    if home == path or home.is_relative_to(path) or socket == path or socket.is_relative_to(path):
        raise ValueError("Home directories and Docker socket paths cannot be mounted")
    if path.is_socket():
        raise ValueError("Socket mounts are unsupported")
    return path


def _mounts(config, session):
    readonly = {
        _mount_path(str(BASE)),
        _mount_path(str(GUARD)),
        _path(config["session"]),
        (_path(session["project"]) / ".claude").resolve(),
    }
    readonly.update(_path(session[key]) for key in ("city_settings", "mcp_config", "prompt_file"))
    for value in config["packs"]:
        pack = _mount_path(value)
        if not (pack / "pack.toml").is_file():
            raise ValueError("Every pack path must contain pack.toml")
        readonly.add(pack)
    readonly.update(_mount_path(value) for value in config["readonly"])
    writable = {_mount_path(value) for value in config["writable"]}
    if readonly & writable:
        raise ValueError("A read-only asset cannot also be writable")
    credentials, claude = _path(config["credentials"]), _path(config["claude"])
    if not credentials.is_file() or not claude.is_file() or not _path(config["runtime"]).is_file():
        raise ValueError("Selected credentials, client and runtime must be files")
    # This is a container path. Host symlinks must not change its destination.
    target = _absolute(config["config_dir"]) / ".credentials.json"
    # Parent writable mounts precede the more specific protected mounts.
    mounts = [(path, path, False) for path in sorted(writable)]
    mounts += [(path, path, True) for path in sorted(readonly)]
    mounts += [(credentials, target, True), (claude, Path("/usr/local/bin/claude"), True)]
    return " ".join(
        f"--mount=type=bind,src={source},dst={target}" + (",readonly" if protected else "")
        for source, target, protected in mounts
    )


def _rules(config, project):
    source = _path(config.get("stack_rules", str(GUARD / "base-rules.json")))
    probe = subprocess.run(
        [sys.executable, str(GUARD / "guard.py"), "--rules", str(source)],
        input=json.dumps(
            {"tool_name": "Read", "tool_input": {"file_path": "README.md"}, "cwd": str(project)}
        ),
        env={**os.environ, "DEVKIT_UNATTENDED": "1"},
        text=True,
        capture_output=True,
        timeout=10,
    )
    if probe.returncode or probe.stdout or probe.stderr:
        raise ValueError("The actual guard must accept the complete base or additive stack rules")
    rules = _json(source)
    branches = rules["rules"]["no-protected-push"]["branches"]
    rules["rules"]["no-protected-push"]["branches"] = list(
        dict.fromkeys([*branches, config["default_branch"], *config["protected_branches"]])
    )
    if len(json.dumps(rules).encode()) > 65536:
        raise ValueError("Combined guard rules exceed the hook's 64 KiB limit")
    return rules


def _settings(project):
    directory = project / ".claude"
    path = directory / "settings.json"
    if not directory.resolve().is_relative_to(project) or not path.resolve().is_relative_to(
        project
    ):
        raise ValueError("Claude settings cannot escape the task project")
    settings = _json(path) if path.exists() else {}
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        raise ValueError("Project settings and hooks must be objects")
    entries = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    if not isinstance(entries, list):
        raise ValueError("PreToolUse hooks must be a list")
    command = shlex.join(
        [
            "python",
            str(GUARD / "guard.py"),
            "--rules",
            str(directory / "devkit-unattended-rules.json"),
        ]
    )
    hook = {"matcher": "*", "hooks": [{"type": "command", "command": command, "timeout": 10}]}
    if hook not in entries:
        entries.append(hook)
    return settings


def _write(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare(path):
    config = _deployment(path)
    session, _ = configuration(_path(config["session"]))
    project = _path(session["project"])
    extra = _mounts(config, session)
    rules, settings = _rules(config, project), _settings(project)
    _write(project / ".claude/devkit-unattended-rules.json", rules)
    _write(project / ".claude/settings.json", settings)
    return {
        "session_provider": "exec:" + str(_path(config["runtime"])),
        "workspace_env": {
            "GC_DOCKER_IMAGE": config["image"],
            "GC_DOCKER_HOME_MOUNT": "false",
            "GC_DOCKER_USER": config["user"],
            "GC_DOCKER_NETWORK": config["network"],
            "GC_DOCKER_EXTRA": extra,
            "CLAUDE_CONFIG_DIR": config["config_dir"],
            "DEVKIT_UNATTENDED": "1",
            "DEVKIT_PACK_BASE": str(BASE),
            "DEVKIT_SESSION_CONFIG": str(_path(config["session"])),
        },
    }


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError("Provide one deployment JSON path")
        print(json.dumps(prepare(_path(sys.argv[1]))))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
        print(
            "Devkit preparation failed; check reviewed paths, branch policy and guard dependencies",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
