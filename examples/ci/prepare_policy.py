"""Create a fresh, explicit CI operator policy for the synthetic combined project."""

import hashlib
import json
import os
import sys
from pathlib import Path


def main(project, wheels):
    os.umask(0o077)
    project, wheels = Path(project).resolve(), Path(wheels).resolve()
    config = Path(os.environ["XDG_CONFIG_HOME"]).resolve() / "devkit"
    if config.is_relative_to(project):
        raise ValueError("Operator configuration must be outside the selected project")
    config.mkdir(parents=True, mode=0o700)  # Refuse to overwrite an existing operator setup.
    policy = []
    for name, version in (("go", "0.1.0"), ("odoo", "0.5.0")):
        wheel = wheels / f"mccann_hub_devkit_{name}-{version}-py3-none-any.whl"
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        policy.extend(
            [
                f"[trusted_plugins.mccann-hub-devkit-{name}]",
                f"version={json.dumps(version)}",
                f"wheel={json.dumps(str(wheel))}",
                f"sha256={json.dumps(digest)}",
            ]
        )
    grants = {
        "go.test": ["read_fs", "write_fs", "execute_process", "network_read", "network_write"],
        "odoo.module.validate": ["read_fs"],
    }
    for command, effects in grants.items():
        policy.extend(
            [
                f"[commands.{json.dumps(command)}]",
                f"project={json.dumps(str(project))}",
                f"effects={json.dumps(effects)}",
                'surfaces=["cli"]',
            ]
        )
    (config / "policy.toml").write_text("\n".join(policy) + "\n")
    (config / "retention.toml").write_text("max_age_days=30\nkeep_last=100\n")


if __name__ == "__main__":
    main(*sys.argv[1:])
