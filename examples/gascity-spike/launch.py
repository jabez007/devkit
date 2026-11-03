"""Launch the subscription-authenticated one-shot session in the test container."""

import json
import os
import subprocess
from pathlib import Path


def main():
    city = Path(__file__).resolve().parent
    arguments = json.loads((city / "claude-arguments.json").read_text())
    environment = dict(os.environ)
    environment.pop("ANTHROPIC_API_KEY", None)
    environment.pop("ANTHROPIC_AUTH_TOKEN", None)
    print("DEVKIT_SPIKE_SESSION_READY", flush=True)
    with (city / "agent.jsonl").open("w") as out, (city / "agent.stderr").open("w") as err:
        result = subprocess.run(arguments, env=environment, stdout=out, stderr=err)
    (city / "agent.exit").write_text(str(result.returncode))


if __name__ == "__main__":
    main()
