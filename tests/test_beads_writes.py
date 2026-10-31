"""Lifecycle commands cross the existing invocation and operator-policy seam."""

import json
import os
from pathlib import Path
from threading import Event, Timer

import pytest
from devkit.app import create_service

from tests.beads_helpers import REF, configure


@pytest.mark.parametrize(
    "operation,fields",
    [
        ("create", {"title": "New task", "description": "Why it matters"}),
        ("claim", {"ref": REF}),
        ("update", {"ref": REF, "title": "Updated", "if_status": "open"}),
        ("comment", {"ref": REF, "text": "Approved synthetic comment"}),
        ("close", {"ref": REF, "reason": "Verified"}),
    ],
)
def test_write_commands_and_evidence(beads_project, operation, fields):
    envelope = create_service(beads_project).execute(
        f"beads.item.{operation}", {"actor": "devkit-test", **fields}
    )
    assert envelope["result"]["status"] == "success", envelope
    assert json.loads(Path(envelope["evidence_path"]).read_text())["result"] == envelope["result"]
    calls = [
        json.loads(line)["argv"]
        for line in (beads_project / "calls.jsonl").read_text().splitlines()
    ]
    writes = [call for call in calls if "--readonly" not in call]
    assert len(writes) == 1
    assert writes[0][:3] == ["--sandbox", "--json", "--actor=devkit-test"]
    assert "--force" not in writes[0]


@pytest.mark.parametrize(
    "operation,fields",
    [
        ("create", {"title": "Task"}),
        ("claim", {"ref": REF}),
        ("update", {"ref": REF, "title": "Updated"}),
        ("comment", {"ref": REF, "text": "Comment"}),
        ("close", {"ref": REF, "reason": "Done"}),
    ],
)
def test_restricted_policy_denies_each_mutation_before_execution(beads_project, operation, fields):
    from devkit_beads import register

    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    text = '[trusted_plugins]\ndevkit-beads="0.2.0"\n'
    for spec in register().commands:
        if spec.id.startswith("beads.item.") and spec.id != "beads.item.show":
            continue
        text += f'[commands."{spec.id}"]\nproject={json.dumps(str(beads_project))}\n'
        text += f'effects={json.dumps(sorted(spec.effects))}\nsurfaces=["cli","python","mcp"]\n'
    policy.write_text(text)
    service = create_service(beads_project)
    result = service.execute(f"beads.item.{operation}", {"actor": "devkit-test", **fields})
    assert result["result"]["reason"] == "DENIED"
    assert not (beads_project / "calls.jsonl").exists()
    assert service.execute("beads.item.show", {"ref": REF})["result"]["status"] == "success"


@pytest.mark.parametrize(
    "operation,fields",
    [
        ("create", {"title": "Task", "force": True}),
        ("claim", {"ref": REF, "force": True}),
        ("update", {"ref": REF, "status": "closed"}),
        ("update", {"ref": REF, "assignee": "other"}),
        ("update", {"ref": REF, "if_status": "open"}),
        ("comment", {"ref": REF, "file": "/secret"}),
        ("close", {"ref": REF, "reason": "Done", "claim_next": True}),
        ("create", {"title": "nul\x00value"}),
    ],
)
def test_write_input_cannot_bypass_separate_commands(beads_project, operation, fields):
    result = create_service(beads_project).execute(
        f"beads.item.{operation}", {"actor": "devkit-test", **fields}
    )
    assert result["result"]["reason"] == "INVALID_INPUT"
    assert not (beads_project / "calls.jsonl").exists()


def test_actor_and_workspace_are_explicit(beads_project):
    service = create_service(beads_project)
    assert (
        service.execute("beads.item.create", {"title": "Task"})["result"]["reason"]
        == "INVALID_INPUT"
    )
    other = REF.replace("36f6082f", "00000000")
    for operation, args in (("create", {"title": "Task"}), ("claim", {})):
        result = service.execute(
            f"beads.item.{operation}", {"actor": "devkit-test", "ref": other, **args}
        )
        assert result["result"]["reason"] == "WORKSPACE_MISMATCH"
    assert not (beads_project / "write-started").exists()


@pytest.mark.parametrize(
    "settings",
    [
        {"write_mode": "malformed"},
        {"write_mode": "oversized"},
        {"write_mode": "exit"},
        {"write_response": {}},
        {"write_response": [{"id": "other-1"}]},
    ],
)
def test_unconfirmed_writes_are_not_replayed(beads_project, settings):
    configure(beads_project, **settings)
    result = create_service(beads_project).execute(
        "beads.item.claim", {"actor": "devkit-test", "ref": REF}
    )
    assert result["result"]["reason"] == "BEADS_WRITE_UNCERTAIN"
    assert result["result"]["data"]["mutation_may_have_occurred"] is True
    calls = [
        json.loads(line)["argv"]
        for line in (beads_project / "calls.jsonl").read_text().splitlines()
    ]
    assert len([call for call in calls if "--readonly" not in call]) == 1


def test_native_guard_failure_preserves_conflict_semantics(beads_project):
    configure(beads_project, write_mode="exit", write_code=13)
    result = create_service(beads_project).execute(
        "beads.item.update",
        {"actor": "devkit-test", "ref": REF, "title": "Change", "if_status": "open"},
    )
    assert result["result"]["status"] == "blocked"
    assert result["result"]["reason"] == "BEADS_CONFLICT"


def test_literal_flag_like_text_is_not_executable_options(beads_project):
    service = create_service(beads_project)
    for operation, fields in (
        ("create", {"title": "--force", "description": "--file=/secret"}),
        ("comment", {"ref": REF, "text": "--force\n--file=/secret"}),
    ):
        assert (
            service.execute(f"beads.item.{operation}", {"actor": "devkit-test", **fields})[
                "result"
            ]["status"]
            == "success"
        )
    writes = [
        json.loads(line)["argv"]
        for line in (beads_project / "calls.jsonl").read_text().splitlines()
        if '"--actor=' in line
    ]
    assert "--title=--force" in writes[0] and "--description=--file=/secret" in writes[0]
    assert writes[1][-2:] == ["--", "--force\n--file=/secret"]


def test_cancellation_during_write_is_not_replayed(beads_project):
    configure(beads_project, write_mode="sleep")
    cancellation = Event()

    # Wait for the child to start rather than racing prerequisite queries.
    def cancel_when_started():
        import time

        for _ in range(100):
            if (beads_project / "write-started").exists():
                cancellation.set()
                return
            time.sleep(0.02)
        cancellation.set()

    timer = Timer(0, cancel_when_started)
    timer.start()
    try:
        result = create_service(beads_project).execute(
            "beads.item.claim", {"ref": REF, "actor": "devkit-test"}, cancellation=cancellation
        )
    finally:
        timer.join()
    assert result["result"]["status"] == "cancelled"
    assert (beads_project / "write-started").exists()


def test_write_success_survives_in_evidence_failure_diagnostic(beads_project, monkeypatch):
    from devkit import invocation

    original = invocation.write_bundle

    def fail_write_result(state, envelope):
        if envelope["command"] == "beads.item.create":
            raise OSError("Synthetic disk failure")
        return original(state, envelope)

    monkeypatch.setattr(invocation, "write_bundle", fail_write_result)
    envelope = create_service(beads_project).execute(
        "beads.item.create", {"actor": "devkit-test", "title": "Task"}
    )
    assert envelope["result"]["reason"] == "EVIDENCE_WRITE_FAILED"
    assert envelope["observed_result"]["status"] == "success"
    assert envelope["observed_result"]["data"]["item"]["ref"] == REF


def test_write_effects_and_administrative_operations(beads_project):
    from devkit_beads import register

    specs = {spec.id: spec for spec in register().commands}
    for operation in ("create", "claim", "update", "comment", "close"):
        assert {"write_fs", "execute_process", "network_write"} <= specs[
            f"beads.item.{operation}"
        ].effects
    assert not any(
        name in specs
        for name in ("beads.delete", "beads.purge", "beads.migrate", "beads.item.force_close")
    )
    path = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    path.write_text(path.read_text().replace(', "network_write"', ""))
    result = create_service(beads_project).execute(
        "beads.item.create", {"actor": "devkit-test", "title": "Task"}
    )
    assert result["result"]["reason"] == "DENIED"
    assert not (beads_project / "calls.jsonl").exists()


def test_lifecycle_cli_python_mcp_parity_and_revocation(beads_project):
    import subprocess

    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    cases = [
        ("create", {"title": "Task"}),
        ("claim", {"ref": REF}),
        ("update", {"ref": REF, "title": "Changed"}),
        ("comment", {"ref": REF, "text": "Synthetic comment"}),
        ("close", {"ref": REF, "reason": "Verified"}),
    ]
    service = create_service(beads_project)

    async def exercise():
        params = StdioServerParameters(
            command=str(Path(".venv/bin/devkit-mcp").resolve()),
            args=["--project", str(beads_project)],
            env=dict(os.environ),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for operation, fields in cases:
                    args = {"actor": "devkit-test", **fields}
                    command = f"beads.item.{operation}"
                    expected = service.execute(command, args)["result"]
                    cli = subprocess.run(
                        [
                            str(Path(".venv/bin/devkit").resolve()),
                            "--project",
                            str(beads_project),
                            "--json",
                            "run",
                            command,
                            "--args",
                            json.dumps(args),
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    assert json.loads(cli.stdout)["result"] == expected
                    result = await session.call_tool(command, args)
                    assert result.structuredContent["result"] == expected
                path = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
                denied_commands = [f"beads.item.{operation}" for operation, _ in cases]
                path.write_text(f"deny={json.dumps(denied_commands)}\n" + path.read_text())
                before = (beads_project / "calls.jsonl").read_bytes()
                for operation, fields in cases:
                    args = {"actor": "devkit-test", **fields}
                    command = f"beads.item.{operation}"
                    denied = await session.call_tool(command, args)
                    assert denied.structuredContent["result"]["reason"] == "DENIED"
                    assert (
                        service.execute(command, args)["result"]
                        == denied.structuredContent["result"]
                    )
                    denied_cli = subprocess.run(
                        [
                            str(Path(".venv/bin/devkit").resolve()),
                            "--project",
                            str(beads_project),
                            "--json",
                            "run",
                            command,
                            "--args",
                            json.dumps(args),
                        ],
                        capture_output=True,
                        text=True,
                    )
                    assert denied_cli.returncode == 2
                    assert (
                        json.loads(denied_cli.stdout)["result"]
                        == denied.structuredContent["result"]
                    )
                assert (beads_project / "calls.jsonl").read_bytes() == before

    anyio.run(exercise)


def test_write_timeout_does_not_retry_or_report_success(beads_project):
    configure(beads_project, write_mode="sleep")
    result = create_service(beads_project, timeout=2).execute(
        "beads.item.claim", {"ref": REF, "actor": "devkit-test"}
    )
    assert result["result"]["status"] == "error"
    assert result["result"]["reason"] == "TIMEOUT"
    assert (beads_project / "write-started").exists()
    calls = [
        json.loads(line)["argv"]
        for line in (beads_project / "calls.jsonl").read_text().splitlines()
    ]
    assert len([call for call in calls if "--readonly" not in call]) == 1
