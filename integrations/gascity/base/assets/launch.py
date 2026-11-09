"""Launch one explicit, subscription-authenticated Claude session for a native pack."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

READY = "DEVKIT_SESSION_READY"
KEYS = {"project", "city_settings", "mcp_config", "prompt_file", "allowed_tools", "artifacts"}
ASSIGNED_BEAD = "assigned_bead"


def _read(path):
    with path.open("rb") as stream:
        content = stream.read(1_000_001)
    if len(content) > 1_000_000:
        raise ValueError("Configuration exceeds limit")
    return content


def _json(path):
    return json.loads(_read(path))


def configuration(path):
    config = _json(path)
    if not isinstance(config, dict) or not KEYS <= set(config) <= KEYS | {ASSIGNED_BEAD}:
        raise ValueError("Expected the documented session configuration")
    if ASSIGNED_BEAD in config and not (
        isinstance(config[ASSIGNED_BEAD], str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", config[ASSIGNED_BEAD])
    ):
        raise ValueError("The assigned bead must be a bead identifier")
    tools = config["allowed_tools"]
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and t for t in tools):
        raise ValueError("Explicit allowed_tools are required")
    for key in KEYS - {"allowed_tools"}:
        if not isinstance(config[key], str) or not Path(config[key]).is_absolute():
            raise ValueError("Session paths must be absolute")
        config[key] = str(Path(config[key]).resolve())
    if not Path(config["project"]).is_dir():
        raise ValueError("Project directory is unavailable")
    native = _json(Path(config["city_settings"]))
    if not {"SessionStart", "UserPromptSubmit"}.issubset(native.get("hooks", {})):
        raise ValueError("Native Gas City hook settings are required")
    if not isinstance(_json(Path(config["mcp_config"])).get("mcpServers"), dict):
        raise ValueError("Explicit project MCP configuration is required")
    prompt = _read(Path(config["prompt_file"]))
    if not prompt:
        raise ValueError("A bounded session prompt is required")
    return config, prompt.decode()


def arguments(config, prompt):
    return [
        "claude",
        "--print",
        prompt,
        "--no-session-persistence",
        "--setting-sources",
        "project",
        "--settings",
        config["city_settings"],
        "--strict-mcp-config",
        "--mcp-config",
        config["mcp_config"],
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-hook-events",
        "--permission-prompts",
        "none",
        "--allowedTools",
        *config["allowed_tools"],
    ]


def run(config, prompt):
    output = Path(config["artifacts"])
    # Native sessions own unique output directories; a rerun cannot overwrite earlier evidence.
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    # Match the checkout helper: inherited Git state must not redirect work to another checkout.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["DEVKIT_UNATTENDED"] = "1"
    if ASSIGNED_BEAD in config:
        # The guard reads this to decide which bead the session may close.
        environment["GC_BEAD_ID"] = config[ASSIGNED_BEAD]
    environment.pop("ANTHROPIC_API_KEY", None)
    environment.pop("ANTHROPIC_AUTH_TOKEN", None)
    with (output / "agent.jsonl").open("w") as out, (output / "agent.stderr").open("w") as err:
        print(READY, flush=True)
        result = subprocess.run(
            arguments(config, prompt),
            cwd=config["project"],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
        )
    (output / "agent.exit").write_text(str(result.returncode))
    return result.returncode


def main():
    try:
        config, prompt = configuration(Path(os.environ["DEVKIT_SESSION_CONFIG"]))
        return run(config, prompt)
    except (KeyError, OSError, ValueError, TypeError, AttributeError):
        print(
            "Devkit session could not start; check the operator-prepared configuration",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
