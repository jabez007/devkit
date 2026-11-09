"""Limit an unattended session's native task commands to reads and its own bead.

Approvals and answers are ordinary bead writes, so a session that can issue any
`gc` or `bd` command can approve its own work. Anything not listed here stays
with the operator.
"""

import os

from _rules import Refusal

BEAD_READS = {"show", "list", "ready", "search", "blocked", "comments"}
CITY_READS = {"prime", "ready", "version", "help"}
PACK_COMMANDS = {
    ("base", "brief"): {"lint", "record", "show", "verify", "resume"},
    ("base", "feedback"): {"questions", "friction", "show"},
}
OWN_BEAD = {"$GC_BEAD_ID", "${GC_BEAD_ID}"}
DENIED = "no-operator-state: this task command belongs to the operator"
NOT_ASSIGNED = "no-operator-state: a session can close only its assigned bead"


def _close_option(word, remaining):
    """Consume one permitted `close` option, including a separate reason value."""
    if word == "--json" or word.startswith("--reason="):
        return True
    if word not in {"--reason", "-r"} or not remaining or remaining[0][1]:
        return False
    remaining.pop(0)
    return True


def _close(arguments, dynamic):
    assigned = os.environ.get("GC_BEAD_ID")
    remaining = list(zip(arguments, dynamic, strict=True))
    targets = 0
    while assigned and remaining:
        word, expands = remaining.pop(0)
        if word in OWN_BEAD or (word == assigned and not expands):
            targets += 1
        # An expanded option could split into extra bead identifiers.
        elif expands or not _close_option(word, remaining):
            raise Refusal(NOT_ASSIGNED)
    if not assigned or targets != 1:
        raise Refusal(NOT_ASSIGNED)


def _bead(words, dynamic):
    if not words or dynamic[0]:
        raise Refusal(DENIED)
    command, *arguments = words
    if command == "close":
        _close(arguments, dynamic[1:])
    elif command not in BEAD_READS or (
        command == "comments" and (arguments[:1] == ["add"] or any(dynamic[1:2]))
    ):
        raise Refusal(DENIED)


def _pack_command_allowed(words):
    if len(words) < 3:
        return False
    if words[1:3] == ["delivery", "report"]:
        return True
    return words[2] in PACK_COMMANDS.get((words[0], words[1]), set())


def _city_command_allowed(words):
    return words[0] in CITY_READS or _pack_command_allowed(words)


def inspect(words, dynamic):
    """Refuse unless a `gc` or `bd` command is on the session's list.

    `dynamic` holds, for each word, whether the shell will expand it.
    """
    if words[0] == "bd":
        _bead(words[1:], dynamic[1:])
        return
    command, expands = words[1:], dynamic[1:]
    if not command:
        return
    if command[0] == "bd" and not expands[0]:
        _bead(command[1:], expands[1:])
    elif any(expands[:3]) or not _city_command_allowed(command):
        raise Refusal(DENIED)
