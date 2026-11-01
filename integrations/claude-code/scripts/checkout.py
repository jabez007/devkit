"""Resolve a project directory without substituting a worktree's main checkout."""

import argparse
import os
import subprocess
from pathlib import Path


def directory(value: str | Path) -> Path:
    result = Path(value).expanduser().resolve(strict=True)
    if not result.is_dir():
        raise ValueError(f"Project is not a directory: {result}")
    return result


def checkout(project: str | None) -> Path:
    if project is not None:
        return directory(project)
    current = Path.cwd().resolve(strict=True)
    # Inherited Git overrides must not redirect discovery to another checkout.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "rev-parse", "--show-toplevel"],
        cwd=current,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    root = directory(result.stdout.rstrip("\n"))
    if not current.is_relative_to(root):
        raise ValueError("Git returned a directory outside the current checkout")
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Explicit directory, including a non-Git subproject")
    args = parser.parse_args()
    try:
        print(checkout(args.project))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(
            2, f"Cannot resolve project: {error}. Select an existing --project directory.\n"
        )


if __name__ == "__main__":
    main()
