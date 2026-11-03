"""Probe hook composition with one denied command; production rules belong to #5."""

import json
import os
import sys
from pathlib import Path


def main():
    event = json.load(sys.stdin)
    command = event.get("tool_input", {}).get("command", "").strip()
    if os.environ.get("DEVKIT_UNATTENDED") != "1" or command != "git push --force":
        return
    (Path.cwd() / ".spike/guard-denied").write_text("DEVKIT_SPIKE_FORCE_PUSH_DENIED\n")
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "DEVKIT_SPIKE_FORCE_PUSH_DENIED",
                }
            }
        )
    )


if __name__ == "__main__":
    main()
