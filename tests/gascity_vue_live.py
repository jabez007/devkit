"""Explicit profile for a guarded Vue session using the matching browser image."""

import shutil
from pathlib import Path

from tests.gascity_live import SESSION_TASK_TOOLS, Profile

ROOT = Path(__file__).resolve().parents[1]
PROFILE = Profile(
    pack=ROOT / "integrations/gascity/vue",
    agent="vue.implementer",
    tools=(
        "Read",
        "Edit",
        "Write",
        *SESSION_TASK_TOOLS,
        "Bash(git *)",
        "Bash(cd *)",
        "Bash(./node_modules/.bin/vitest *)",
        "Bash(./node_modules/.bin/eslint *)",
        "Bash(./node_modules/.bin/vue-tsc *)",
        "Bash(./node_modules/.bin/playwright *)",
    ),
    instructions=(
        "Use ./node_modules/.bin/vitest run, ./node_modules/.bin/eslint, "
        "./node_modules/.bin/vue-tsc --noEmit and ./node_modules/.bin/playwright test "
        "for project checks. These installed tools and browsers are already prepared. "
        "Do not use npm, npx, global binaries or install dependencies. Add a behavior "
        "test for repeated activations. The controller runs all four gates after "
        "you finish. Do not run gc vue delivery check inside this session. "
    ),
    config_dir="/home/ubuntu/.claude",
    path="/opt/devkit/bin:/usr/local/bin:/usr/bin:/bin",
)


def prepare_project(project):
    shutil.copy2(
        ROOT / "integrations/unattended/requirements.txt",
        project / ".devcontainer/guard-requirements.txt",
    )
