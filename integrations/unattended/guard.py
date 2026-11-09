"""Opt-in standalone Claude PreToolUse guard; allowed requests receive no grant."""

import fnmatch
import json
import os
import signal
import sys
from pathlib import Path

from _rules import Refusal, check_git_metadata_write, load

MCP_FILE_READS = {
    "read_file",
    "read_text_file",
    "read_media_file",
    "get_file_info",
    "list_directory",
    "list_directory_with_sizes",
    "directory_tree",
    "search_files",
}
MCP_FILE_WRITES = {"write_file", "append_file", "edit_file", "create_directory"}
MCP_REMOTE_WRITES = {
    "git_push",
    "push_files",
    "create_branch",
    "create_or_update_file",
    "delete_file",
    "update_pull_request_branch",
}


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
    if (
        operation
        in {
            "pull_request_review_write",
            "create_and_submit_pull_request_review",
            "create_pull_request_review",
            "submit_pending_pull_request_review",
        }
        and str(arguments.get("event", "")).upper() == "APPROVE"
    ):
        raise Refusal("no-pr-publish: PR approval requires human review")
    if operation == "create_pull_request" and arguments.get("draft") is not True:
        raise Refusal("no-pr-publish: unattended PR creation must be a draft")
    if (
        operation in {"update_pull_request", "update_pull_request_draft_state"}
        and "draft" in arguments
        and arguments["draft"] is not True
    ):
        raise Refusal("no-pr-publish: PR readiness requires human review")


def _mcp_paths(operation, arguments):
    if operation == "read_multiple_files":
        paths = arguments.get("paths")
        if not isinstance(paths, list):
            raise Refusal("guard-input: MCP batch paths must be a list")
        return [(path, False) for path in paths]
    if operation in {"move_file", "copy_file"}:
        return [
            (arguments["source"], operation == "move_file"),
            (arguments["destination"], True),
        ]
    if operation in MCP_FILE_READS | MCP_FILE_WRITES:
        return [(arguments["path"], operation in MCP_FILE_WRITES)]
    return []


def _mcp_file(value, writable, cwd, credentials):
    # The server's working directory can differ from the Claude request's cwd.
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise Refusal("guard-input: MCP filesystem paths must be absolute")
    # Filesystem tools receive literal paths, not shell-expanded arguments.
    target = Path(value).resolve()
    _credential_check(str(target), cwd, credentials)
    if writable:
        check_git_metadata_write(target)


def _mcp(tool, arguments, cwd, credentials):
    if not tool.startswith("mcp__"):
        return
    operation = tool.rsplit("__", 1)[-1]
    if operation in {"delete_branch", "delete_ref"}:
        raise Refusal("no-remote-delete: remote branches cannot be deleted")
    if operation in MCP_REMOTE_WRITES:
        if arguments.get("force") or arguments.get("force_with_lease"):
            raise Refusal("no-force-push: forced remote writes are forbidden")
        # An MCP owner/repo need not match cwd. Local Git metadata cannot prove
        # that this remote target is an unprotected, non-default branch.
        raise Refusal("no-protected-push: use an inspected explicit Git push instead of MCP writes")
    for value, writable in _mcp_paths(operation, arguments):
        _mcp_file(value, writable, cwd, credentials)


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
    _mcp(tool, arguments, cwd, credentials)
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
