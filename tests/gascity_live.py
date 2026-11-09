"""Real guarded one-shot sessions shared by the stack acceptance fixtures."""

import json
import os
import re
import shlex
import subprocess
import sys
import time
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "integrations/gascity/base"


# Only what an implementation session needs; approvals and answers stay with the operator.
SESSION_TASK_TOOLS = (
    "Bash(gc base brief verify *)",
    "Bash(gc base brief show *)",
    "Bash(gc base feedback questions *)",
    "Bash(gc base feedback friction *)",
    "Bash(gc base feedback show *)",
    "Bash(gc bd show *)",
    "Bash(gc bd list *)",
    "Bash(gc bd comments *)",
    "Bash(gc bd close *)",
)


@dataclass(frozen=True)
class Profile:
    pack: Path
    agent: str
    tools: tuple[str, ...]
    instructions: str
    config_dir: str
    path: str


def implement(city, root, task, attempt, profile):
    city.root_id = root
    city.artifacts = (
        city.city / "session-artifacts" / (root + "-" + attempt + "-" + uuid.uuid4().hex[:8])
    )
    city.args.devcontainer = Path(os.environ["DEVKIT_DEVCONTAINER"]).resolve()
    city.build_container()
    original = city.env.copy()
    try:
        _prepare(city, root, task, attempt, profile)
        city.gc(
            "session",
            "new",
            profile.agent,
            "--alias",
            "devkit-live",
            "--title",
            "Disposable delivery qualification",
            "--no-attach",
            "--json",
            structured=True,
        )
        _preflight(city, root, task, profile)
        _finished(city)
    finally:
        subprocess.run(
            [str(city.args.gc), "--city", str(city.city), "session", "close", "devkit-live"],
            env=city.env,
            capture_output=True,
            timeout=60,
        )
        city.env = original
        subprocess.run(["docker", "image", "rm", city.image], capture_output=True)


def _prepare(city, root, task, attempt, profile):
    bound = city.gc("bd", "show", root, "--json", structured=True)[0]["metadata"]
    (city.worktree / ".mcp.json").write_text('{"mcpServers":{}}\n')
    prompt = city.root / "implementation.md"
    prompt.write_text(
        (profile.pack / "agents/implementer/prompt.template.md").read_text()
        + f"\nSelected task: {task}. Workflow root: {root}. Assigned attempt: {attempt}.\n"
        + f"City directory: {city.city}. Worktree: {city.worktree}.\n"
        + f"Delivery round: {bound.get('devkit.feedback.round', 1)}. "
        + f"Session artifacts: {city.artifacts}.\n"
        + f"Previous check bundle: {bound.get('devkit.delivery.checks', 'none')}.\n"
        + "This is a disposable test repository. Stay in its worktree and use the inherited "
        "native city context to verify approval and read the approved brief. Do not cd "
        "outside the worktree or add a --city flag to pack commands. "
        + profile.instructions
        + "The operator has configured this disposable repository's Git identity. "
        "Commit your changes with ordinary git commit. Do not pass Git global -c options "
        "or override GIT_* environment variables; the shared guard forbids those. "
        "Close only the assigned attempt after a clean commit. Do not push or publish.\n"
    )
    session = city.root / "session.json"
    session.write_text(
        json.dumps(
            dict(
                project=str(city.worktree),
                city_settings=str(city.city / ".gc/settings.json"),
                mcp_config=str(city.worktree / ".mcp.json"),
                prompt_file=str(prompt),
                allowed_tools=list(profile.tools),
                artifacts=str(city.artifacts),
                assigned_bead=attempt,
            )
        )
    )
    writable = [city.root / name for name in ("control", "cache", "config", "state")]
    for path in writable:
        path.mkdir(parents=True, exist_ok=True)
    deployment = city.root / "deployment.json"
    deployment.write_text(
        json.dumps(
            dict(
                session=str(session),
                claude=str(Path(os.environ["DEVKIT_CLAUDE"]).resolve()),
                credentials=str(Path(os.environ["DEVKIT_CLAUDE_CREDENTIALS"]).resolve()),
                config_dir=profile.config_dir,
                runtime=str(city.args.gascity_source / "scripts/gc-session-docker"),
                image=city.image,
                user=f"{os.getuid()}:{os.getgid()}",
                network="host",
                packs=[
                    str(profile.pack),
                    str(city.args.gascity_source / "internal/bootstrap/packs/core"),
                    str(city.args.gascity_source / "examples/bd"),
                ],
                readonly=[
                    str(city.args.gc),
                    str(city.args.bd),
                    str(city.args.dolt),
                    str(city.root / "dolt"),
                    *([str(city.root / "operator")] if (city.root / "operator").is_dir() else []),
                    bound["devkit.delivery.job"],
                    bound["devkit.brief.path"],
                    *(
                        [str(Path(bound["devkit.delivery.checks"]).parent)]
                        if bound.get("devkit.delivery.checks")
                        else []
                    ),
                ],
                writable=list(map(str, writable)),
                default_branch="main",
                protected_branches=[],
            )
        )
    )
    _migrate_guard(city)
    prepared = city.run(sys.executable, BASE / "assets/prepare.py", deployment, structured=True)
    # Native Beads verifies local process identity before adopting a proxy. Give the
    # container its own proxy root, with the host's authoritative proxy as upstream.
    endpoint = json.loads((city.city / ".beads/dolt/proxy.pid").read_text())
    client_profile = city.root / "container-beads.json"
    client_profile.write_text(
        json.dumps(
            dict(
                root_path="/tmp/devkit-beads-client-" + root,
                external=dict(host="127.0.0.1", port=endpoint["port"], user="root"),
                idle_timeout=0,
            )
        )
    )
    client_profile.chmod(0o600)
    target = city.city / ".beads/proxied_server_client_info.json"
    prepared["workspace_env"]["GC_DOCKER_EXTRA"] += (
        f" --mount=type=bind,src={client_profile},dst={target},readonly"
    )
    city.env.update(GC_SESSION=prepared["session_provider"], DEVKIT_UNATTENDED="1")
    _workspace_environment(
        city.city / "city.toml",
        {
            **prepared["workspace_env"],
            **{
                key: city.env[key]
                for key in ("GC_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME")
            },
            "PATH": ":".join(
                [
                    str(city.args.gc.parent),
                    str(city.args.bd.parent),
                    str(city.args.dolt.parent),
                    profile.path,
                ]
            ),
            "DOLT_ROOT_PATH": str(city.root / "dolt"),
            "DO_NOT_TRACK": "1",
            "BD_DISABLE_METRICS": "1",
        },
    )


def _workspace_environment(path, values):
    text = path.read_text()
    previous = tomllib.loads(text).get("workspace", {}).get("env", {})
    merged = {**previous, **values}
    assert all(isinstance(value, str) for value in merged.values())
    section = "[workspace.env]\n" + "".join(
        f"{key}={json.dumps(value)}\n" for key, value in merged.items()
    )
    matches = list(re.finditer(r"(?m)^\[workspace\.env\][ \t]*(?:#[^\n]*)?$", text))
    assert len(matches) <= 1
    if matches:
        begin = matches[0]
        following = re.search(r"(?m)^\[", text[begin.end() :])
        end = begin.end() + following.start() if following else len(text)
        text = text[: begin.start()] + section + "\n" + text[end:]
    else:
        text += "\n" + section
    path.write_text(text)


def _migrate_guard(city):
    previous = (
        tomllib.loads((city.city / "city.toml").read_text()).get("workspace", {}).get("env", {})
    )
    old_base = previous.get("DEVKIT_PACK_BASE")
    settings_path = city.worktree / ".claude/settings.json"
    if not old_base or old_base == str(BASE) or not settings_path.exists():
        return
    old_guard = Path(old_base).parent.parent / "unattended/guard.py"
    command = shlex.join(
        [
            "python",
            str(old_guard),
            "--rules",
            str(city.worktree / ".claude/devkit-unattended-rules.json"),
        ]
    )
    old_entry = {"matcher": "*", "hooks": [{"type": "command", "command": command, "timeout": 10}]}
    settings = json.loads(settings_path.read_text())
    entries = settings.get("hooks", {}).get("PreToolUse", [])
    settings.setdefault("hooks", {})["PreToolUse"] = [
        entry for entry in entries if entry != old_entry
    ]
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")


def _preflight(city, root, task, profile):
    containers = city.run(
        "docker", "ps", "--filter", "ancestor=" + city.image, "--format", "{{.ID}}", cwd=city.root
    ).splitlines()
    assert len(containers) == 1
    prefix = ["docker", "exec", "--workdir", str(city.worktree), containers[0]]
    _guard_preflight(city, prefix, profile)
    outputs = []
    for command in (
        [
            "python3",
            "-c",
            "import os,pathlib,tempfile,bashlex; "
            "p=pathlib.Path(os.environ['CLAUDE_CONFIG_DIR']); "
            "assert os.access(p/'.credentials.json',os.R_OK), 'Credential file is not readable'; "
            "t=tempfile.TemporaryDirectory(prefix='devkit-preflight-',dir=p); t.cleanup(); "
            "print('Selected subscription file is readable and session directory is writable')",
        ],
        ["gc", "--city", str(city.city), "bd", "show", root, "--json"],
        ["gc", "base", "brief", "verify", "--workflow", root, "--task", task],
    ):
        result = subprocess.run([*prefix, *command], capture_output=True, text=True, timeout=60)
        outputs.append(
            dict(
                command=command,
                code=result.returncode,
                stdout=result.stdout[-4000:],
                stderr=result.stderr[-4000:],
            )
        )
    (city.root / "container-preflight.json").write_text(json.dumps(outputs, indent=2))
    assert all(result["code"] == 0 for result in outputs), outputs


def _guard_preflight(city, prefix, profile):
    command = [
        "python",
        str(ROOT / "integrations/unattended/guard.py"),
        "--rules",
        str(city.worktree / ".claude/devkit-unattended-rules.json"),
    ]
    observations = []
    for path in ("README.md", str(Path(profile.config_dir) / ".credentials.json")):
        event = dict(tool_name="Read", tool_input=dict(file_path=path), cwd=str(city.worktree))
        result = subprocess.run(
            [prefix[0], prefix[1], "--interactive", *prefix[2:], *command],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            timeout=15,
        )
        observations.append(
            dict(code=result.returncode, stdout=result.stdout, stderr=result.stderr)
        )
    (city.root / "container-guard-preflight.json").write_text(json.dumps(observations, indent=2))
    allowed, refused = observations
    assert allowed == dict(code=0, stdout="", stderr=""), allowed
    assert refused["code"] == 0 and refused["stderr"] == "", refused
    denial = json.loads(refused["stdout"])["hookSpecificOutput"]
    assert denial["permissionDecision"] == "deny"
    assert denial["permissionDecisionReason"].startswith("no-credential-access:"), denial


def _finished(city):
    deadline = time.monotonic() + 600
    while not (city.artifacts / "agent.exit").exists():
        if time.monotonic() > deadline:
            raise AssertionError("The live implementation did not finish within ten minutes")
        time.sleep(0.5)
    assert (city.artifacts / "agent.exit").read_text() == "0", (
        "Live session failed; inspect " + str(city.artifacts)
    )
    events = [
        json.loads(line) for line in (city.artifacts / "agent.jsonl").read_text().splitlines()
    ]
    results = [event for event in events if event.get("type") == "result"]
    assert results and not results[-1].get("is_error"), results
    hooks = [
        event
        for event in events
        if event.get("subtype") == "hook_response"
        and event.get("hook_event") in {"SessionStart", "UserPromptSubmit"}
    ]
    assert {event["hook_event"] for event in hooks} == {"SessionStart", "UserPromptSubmit"}
    assert all(event.get("exit_code") == 0 for event in hooks)
