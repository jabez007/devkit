"""Repository-local helpers for plugin tests; copy with a plugin's test suite."""

import json
from pathlib import Path

from mccann_hub.devkit.contracts import CommandSpec
from mccann_hub.devkit.invocation import CommandService
from mccann_hub.devkit.policy import Policy


def service_with_grants(settings, commands: tuple[CommandSpec, ...]):
    """Explicitly authorize test commands for the temporary project's Python surface."""
    grants = {
        spec.id: {
            "project": str(settings.project_root),
            "effects": list(spec.effects),
            "surfaces": ["python"],
        }
        for spec in commands
    }
    return CommandService(settings, commands, Policy(commands=grants))


def assert_success(service, command, arguments, expected_data):
    """Exercise validation, authorization, execution, and persisted evidence together."""
    envelope = service.execute(command, arguments)
    assert envelope["result"]["status"] == "success", envelope["result"]
    assert envelope["result"]["data"] == expected_data
    persisted = json.loads(Path(envelope["evidence_path"]).read_text())
    assert persisted["result"] == envelope["result"]
    assert persisted["run_id"] == envelope["run_id"]
    return envelope
