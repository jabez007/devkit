"""A failed command or an agent narrative cannot qualify hook enforcement."""

import copy
import runpy
from pathlib import Path

import pytest

DRIVER = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check_gascity_spike.py"))


def events():
    return [
        {
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "push",
                        "name": "Bash",
                        "input": {"command": "git push --force"},
                    }
                ]
            }
        },
        {
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "push",
                        "is_error": True,
                        "content": "Blocked: no-force-push",
                    }
                ]
            }
        },
    ]


def check(transcript):
    DRIVER["require_tool_denial"](
        transcript, "Bash", {"command": "git push --force"}, "no-force-push"
    )


def test_guard_evidence_accepts_matching_denial():
    check(events())


def test_guard_evidence_accepts_optional_tool_descriptions():
    transcript = events()
    transcript[0]["message"]["content"][0]["input"]["description"] = "Probe the guard"
    check(transcript)


@pytest.mark.parametrize(
    "change",
    [
        {"tool_use_id": "unrelated"},
        {"is_error": False},
        {"content": "fatal: no configured push destination"},
    ],
)
def test_guard_evidence_rejects_unrelated_or_executed_commands(change):
    transcript = events()
    transcript[1]["message"]["content"][0].update(change)
    with pytest.raises(DRIVER["QualificationFailed"]):
        check(transcript)


def test_guard_evidence_requires_exactly_one_probe_and_result():
    transcript = events()
    with pytest.raises(DRIVER["QualificationFailed"]):
        check(transcript[:1])
    with pytest.raises(DRIVER["QualificationFailed"]):
        check([*transcript, copy.deepcopy(transcript[0])])


def test_guard_evidence_requires_the_requested_input():
    transcript = events()
    transcript[0]["message"]["content"][0]["input"]["command"] = "git status"
    with pytest.raises(DRIVER["QualificationFailed"]):
        check(transcript)
