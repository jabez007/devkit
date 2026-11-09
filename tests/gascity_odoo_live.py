"""Project image and operator profile for the live first-stack acceptance."""

import shutil
from pathlib import Path

from tests.gascity_live import SESSION_TASK_TOOLS, Profile

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/gascity-spike"
PROFILE = Profile(
    pack=ROOT / "integrations/gascity/odoo",
    agent="odoo.implementer",
    tools=(
        "Read",
        "Edit",
        "Write",
        *SESSION_TASK_TOOLS,
        "Bash(cd *)",
        "Bash(git *)",
        "Bash(devkit-odoo *)",
    ),
    instructions=(
        "Add a native test for the approved behavior. Run the offline validator. "
        "The controller runs full Odoo tests after you finish. Do not run the delivery "
        "check command inside this session. The existing test image has the runtime tools. "
    ),
    config_dir="/home/spike/.claude",
    path="/usr/local/bin:/usr/bin:/bin",
)


def devcontainer(project):
    build = project / ".devcontainer"
    build.mkdir()
    for name in ("Dockerfile", "devcontainer.json"):
        shutil.copy2(FIXTURE / name, build / name)
    shutil.copy2(
        ROOT / "integrations/unattended/requirements.txt", build / "guard-requirements.txt"
    )
    with (project / ".gitignore").open("a") as stream:
        stream.write(".devcontainer/wheels/\n.devcontainer/constraints.txt\n")
