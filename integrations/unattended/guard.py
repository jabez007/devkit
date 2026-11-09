"""Opt-in standalone Claude PreToolUse guard; allowed requests receive no grant."""

import fnmatch
import json
import os
import signal
import sys
from pathlib import Path

from _rules import Refusal, check_git_metadata_write, load


def _credential_paths(rules):
    paths = rules["no-credential-access"]["paths"]
    if directory := os.environ.get("CLAUDE_CONFIG_DIR"):
        paths = [*paths, str(Path(directory) / ".credentials.json")]
    return [Path(os.path.expandvars(path)).expanduser().resolve() for path in paths]


def _path(value, cwd):
    return (cwd / Path(os.path.expandvars(value)).expanduser()).resolve()


def _credential_check(value, cwd, credentials):
    target = _path(value, cwd)
    if ".credentials.json" in value or any(
        path == target or path.is_relative_to(target) or fnmatch.fnmatchcase(str(path), str(target))
        for path in credentials
    ):
        raise Refusal("no-credential-access: subscription credentials cannot be accessed")


def _publication(tool, arguments):
    operation = tool.rsplit("__", 1)[-1]
    if operation in {"merge_pull_request", "mark_pull_request_ready_for_review"}:
        raise Refusal("no-pr-publish: PR readiness and merge require human review")
    if operation == "pull_request_review_write" and arguments.get("event") == "APPROVE":
        raise Refusal("no-pr-publish: PR approval requires human review")
    if operation == "create_pull_request" and arguments.get("draft") is not True:
        raise Refusal("no-pr-publish: unattended PR creation must be a draft")


def inspect(event, rules):
    from _shell import inspect as inspect_shell

    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        raise Refusal("guard-input: expected a tool request")
    tool, arguments = event.get("tool_name"), event["tool_input"]
    if not isinstance(tool, str) or not isinstance(event.get("cwd"), str):
        raise Refusal("guard-input: tool name and working directory are required")
    cwd = Path(event["cwd"]).resolve()
    credentials = _credential_paths(rules)
    if arguments.get("run_in_background"):
        raise Refusal("no-background: background tool execution is forbidden")
    _publication(tool, arguments)
    if tool in {"Read", "Edit", "Write", "NotebookEdit"}:
        value = arguments.get("file_path", arguments.get("notebook_path", ""))
        _credential_check(value, cwd, credentials)
        if tool != "Read":
            check_git_metadata_write(_path(value, cwd))
    if tool in {"Glob", "Grep"}:
        target = _path(arguments.get("path", str(cwd)), cwd)
        if any(path == target or path.is_relative_to(target) for path in credentials):
            raise Refusal("no-credential-access: search scope includes subscription credentials")
    if tool == "Bash":
        command = arguments.get("command")
        if not isinstance(command, str):
            raise Refusal("guard-input: Bash command must be a string")
        inspect_shell(command, cwd, rules, lambda word: _credential_check(word, cwd, credentials))


def deny(reason):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def _deadline(signum, frame):
    raise Refusal("guard-timeout: inspection exceeded five seconds")


def main():
    if "DEVKIT_UNATTENDED" not in os.environ:
        return
    signal.signal(signal.SIGALRM, _deadline)
    signal.setitimer(signal.ITIMER_REAL, 5)
    try:
        arguments = sys.argv[1:]
        if arguments and (len(arguments) != 2 or arguments[0] != "--rules"):
            raise Refusal("guard-config: expected --rules followed by a reviewed rules file")
        rules = load(Path(arguments[1]) if arguments else None)
        raw = sys.stdin.buffer.read(1_048_577)
        if len(raw) > 1_048_576:
            raise Refusal("guard-input: tool request exceeds 1 MiB")
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeError):
            raise Refusal("guard-input: malformed JSON tool request") from None
        inspect(event, rules)
    except Refusal as exc:
        deny(str(exc))
    except Exception:
        # Hook failures must not silently permit the pending tool call.
        deny("guard-error: unattended inspection could not complete")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == "__main__":
    main()
