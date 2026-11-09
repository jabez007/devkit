"""Inspect literal Git push destinations without contacting a remote."""

import fnmatch
import os
import shlex
import subprocess

from _rules import Refusal, check_prefix

# Git runs these itself and never lets an alias replace them. Any other name is an
# alias or an external git-* program, such as subtree, which pushes on its own.
KNOWN_COMMANDS = {
    "add", "am", "apply", "archive", "bisect", "blame", "branch", "bundle", "cat-file",
    "check-attr", "check-ignore", "check-mailmap", "check-ref-format", "checkout", "cherry",
    "cherry-pick", "clean", "clone", "commit", "commit-tree", "count-objects", "describe",
    "diff", "diff-files", "diff-index", "diff-tree", "fetch", "for-each-ref", "format-patch",
    "fsck", "gc", "grep", "hash-object", "help", "init", "log", "ls-files", "ls-remote",
    "ls-tree", "merge", "merge-base", "merge-file", "mv", "name-rev", "notes", "pull",
    "rebase", "reflog", "remote", "repack", "replace", "rerere", "reset", "restore",
    "rev-list", "rev-parse", "revert", "rm", "shortlog", "show", "show-branch", "show-ref",
    "sparse-checkout", "stash", "status", "switch", "symbolic-ref", "tag", "update-index",
    "update-ref", "var", "verify-commit", "verify-tag", "version", "worktree", "write-tree",
}  # fmt: skip
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l"}
CONFIG_SCOPES = {"--local", "--global", "--worktree"}
SESSION_CONFIG = {"user.name", "user.email"}


def read(cwd, *arguments):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", *arguments],
            cwd=cwd,
            env=environment,
            text=True,
            capture_output=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Refusal("no-protected-push: Git metadata is unavailable") from None
    return result.stdout.strip() if result.returncode == 0 else None


def _arguments(words, cwd):
    arguments = words[1:]
    while arguments and arguments[0].startswith("-"):
        option = arguments.pop(0)
        if option in {"--version", "--help", "-h"}:
            return [], cwd
        if option == "-C" and arguments:
            cwd = (cwd / arguments.pop(0)).resolve()
        elif option not in {"--no-pager", "--no-optional-locks"}:
            raise Refusal("literal-shell: unsupported Git global option")
    return arguments, cwd


def _short_option(argument, letter):
    return argument.startswith("-") and not argument.startswith("--") and letter in argument[1:]


def _force(arguments):
    for argument in arguments:
        option = argument.split("=", 1)[0]
        if argument.startswith("+") or _short_option(argument, "f"):
            return True
        if option.startswith("--force") or option == "--mirror":
            return True
        if option.startswith("--") and len(option) > 2 and "--force".startswith(option):
            return True
    return False


def _deletes(arguments):
    return any(
        arg.startswith(":")
        or _short_option(arg, "d")
        or arg in {"--delete", "--prune"}
        or (arg.startswith("--") and len(arg) > 2 and "--delete".startswith(arg))
        for arg in arguments
    )


def _push_targets(arguments):
    positional = []
    for argument in arguments:
        if argument in {
            "-u",
            "--set-upstream",
            "-n",
            "--dry-run",
            "--porcelain",
            "-q",
            "--quiet",
            "-v",
            "--verbose",
            "--atomic",
        }:
            continue
        if argument.startswith("-"):
            raise Refusal("no-protected-push: unsupported push option")
        positional.append(argument)
    if len(positional) < 2:
        raise Refusal("no-protected-push: provide an explicit remote and destination")
    return positional[0], positional[1:]


def _destination(refspec, cwd):
    destination = refspec.split(":", 1)[-1]
    if destination in {"HEAD", "@"}:
        destination = read(cwd, "symbolic-ref", "--quiet", "--short", "HEAD") or ""
    # Git also resolves heads/<name> on the remote, so both prefixes name a branch.
    destination = destination.removeprefix("refs/heads/").removeprefix("heads/")
    if (
        not destination
        or "//" in destination
        or ".." in destination
        or destination.startswith("/")
        or any(char in destination for char in "$`*?[]{}~^\\")
    ):
        raise Refusal("no-protected-push: push destination is not a literal branch")
    return destination


def inspect(words, cwd, rules, depth=0):
    arguments, cwd = _arguments(words, cwd)
    if not arguments:
        return
    command, *arguments = arguments
    check_prefix(["git", command, *arguments], rules)
    if command in {"push", "send-pack", "http-push"}:
        _inspect_push(arguments, cwd, rules)
    elif command == "config":
        _inspect_config(arguments)
    elif command not in KNOWN_COMMANDS:
        _inspect_alias(command, arguments, cwd, rules, depth)


def _inspect_config(arguments):
    """Refuse writes, because a later command in the request would obey them unseen."""
    options = {argument for argument in arguments if argument.startswith("-")}
    names = [argument for argument in arguments if not argument.startswith("-")]
    if options & CONFIG_READS or names[:1] in (["get"], ["list"]):
        return
    if options <= CONFIG_SCOPES and (
        len(names) == 1 or (len(names) == 2 and names[0].lower() in SESSION_CONFIG)
    ):
        return
    raise Refusal("no-operator-state: Git configuration cannot be changed")


def _inspect_alias(command, arguments, cwd, rules, depth):
    alias = read(cwd, "config", "--get", f"alias.{command}")
    if not alias:
        raise Refusal("literal-shell: unknown Git command")
    if depth >= 4 or alias.startswith("!"):
        raise Refusal("literal-shell: shell or recursive Git alias")
    inspect(["git", *shlex.split(alias), *arguments], cwd, rules, depth + 1)


def _refuse_configured_mapping(remote, cwd):
    """Git applies these to a push that names only a source, moving its destination."""
    if read(cwd, "config", "--get", f"remote.{remote}.push") or read(
        cwd, "config", "--get", "push.default"
    ) in {"upstream", "tracking"}:
        raise Refusal("no-protected-push: configured push mapping can change the destination")


def _inspect_push(arguments, cwd, rules):
    if _force(arguments):
        raise Refusal("no-force-push: force or mirror push is forbidden")
    if _deletes(arguments):
        raise Refusal("no-remote-delete: remote ref deletion is forbidden")
    remote, targets = _push_targets(arguments)
    if read(cwd, "config", "--bool", "--get", f"remote.{remote}.mirror") == "true":
        raise Refusal("no-force-push: remote is configured for mirror pushes")
    _refuse_configured_mapping(remote, cwd)
    default = read(cwd, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD")
    if not default:
        raise Refusal("no-protected-push: remote default branch is unknown")
    protected = [default.removeprefix(remote + "/"), *rules["no-protected-push"]["branches"]]
    for refspec in targets:
        destination = _destination(refspec, cwd)
        if any(fnmatch.fnmatchcase(destination, pattern) for pattern in protected):
            raise Refusal("no-protected-push: destination is a default or protected branch")
