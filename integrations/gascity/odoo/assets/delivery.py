"""Native delivery entrypoint using this stack's check adapter."""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / "base"
sys.path.insert(0, str(BASE / "assets"))

import checks  # noqa: E402
from delivery_state import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(checks))
