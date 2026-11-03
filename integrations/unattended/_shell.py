"""Visit real Bash syntax, including nested substitutions, without executing it."""

from pathlib import Path

import bashlex
from _git import inspect as inspect_git
from _rules import Refusal, check_prefix

LAUNCHERS = {
    "timeout": {
        "values": {"-s", "--signal", "-k", "--kill-after"},
        "flags": {"--foreground", "--preserve-status", "--verbose"},
        "positional": 1,
    },
    "nice": {"values": {"-n", "--adjustment"}, "flags": set(), "positional": 0},
    "stdbuf": {
        "values": {"-i", "--input", "-o", "--output", "-e", "--error"},
        "flags": set(),
        "positional": 0,
    },
}


def _launcher(program, arguments):
    options = LAUNCHERS[program]
    while arguments and arguments[0].startswith("-"):
        argument = arguments.pop(0)
        name, separator, _ = argument.partition("=")
        if name == "--":
            break
        if name in options["flags"]:
            continue
        if name in options["values"]:
            if not separator and arguments:
                arguments.pop(0)
        elif not any(
            option.startswith("-")
            and not option.startswith("--")
            and argument.startswith(option)
            and len(argument) > len(option)
            for option in options["values"]
        ):
            raise Refusal("literal-shell: unsupported launcher option")
    if len(arguments) <= options["positional"]:
        raise Refusal("literal-shell: launcher must name its command")
    return arguments[options["positional"] :]


def _assignment(word):
    name = word.split("=", 1)[0]
    if name.startswith(("GIT_", "GH_", "DEVKIT_", "CLAUDE_")) or name in {
        "PATH",
        "BASH_ENV",
        "ENV",
        "SHELLOPTS",
    }:
        raise Refusal("literal-shell: command cannot override the guarded runtime environment")


def _unwrap(words):
    while words:
        words[0] = Path(words[0]).name
        if words[0] in LAUNCHERS:
            words = _launcher(words[0], words[1:])
            continue
        if words[0] not in {"env", "command", "exec", "builtin"}:
            break
        wrapper, *words = words
        while words and ("=" in words[0] if wrapper == "env" else words[0] in {"--", "-p"}):
            if wrapper == "env":
                _assignment(words[0])
            words = words[1:]
        if words and words[0].startswith("-"):
            raise Refusal("literal-shell: unsupported command wrapper")
    return words


def _draft(arguments):
    draft = False
    values = {
        "--title",
        "-t",
        "--body",
        "-b",
        "--body-file",
        "-F",
        "--base",
        "-B",
        "--head",
        "-H",
        "--repo",
        "-R",
        "--label",
        "-l",
        "--assignee",
        "-a",
        "--reviewer",
        "-r",
        "--milestone",
        "-m",
        "--template",
        "-T",
    }
    flags = {"--fill", "-f", "--fill-first", "--fill-verbose", "--no-maintainer-edit"}
    arguments = list(arguments)
    while arguments:
        argument = arguments.pop(0)
        name, separator, value = argument.partition("=")
        if name in {"--draft", "-d"}:
            draft = not separator or value == "true"
        elif name in values:
            if not separator and arguments:
                arguments.pop(0)
        elif name not in flags:
            raise Refusal("literal-shell: unsupported PR creation option")
    return draft


def _pr(words):
    if len(words) > 1 and words[1].startswith("-"):
        raise Refusal("literal-shell: put GH repository options after the PR operation")
    if len(words) < 3 or words[1] != "pr":
        if len(words) > 1 and words[1] == "api":
            raise Refusal("no-pr-publish: use explicit PR commands instead of raw API calls")
        if words[1:3] == ["repo", "sync"]:
            raise Refusal("no-force-push: repository synchronization may overwrite remote branches")
        if len(words) > 1 and words[1] not in {
            "issue",
            "repo",
            "run",
            "workflow",
            "auth",
            "version",
            "status",
            "search",
            "label",
        }:
            raise Refusal("literal-shell: GH aliases and extensions cannot be inspected")
        return
    operation, *arguments = words[2:]
    if operation in {"merge", "ready"}:
        raise Refusal("no-pr-publish: PR readiness and merge require human review")
    if operation == "review" and any(
        arg.split("=", 1)[0] in {"--approve", "-a"} for arg in arguments
    ):
        raise Refusal("no-pr-publish: PR approval requires human review")
    if operation == "create" and not _draft(arguments):
        raise Refusal("no-pr-publish: unattended PR creation must be a draft")


class Inspection(bashlex.ast.nodevisitor):
    def __init__(self, cwd, rules, credential_check, depth):
        self.cwd = cwd
        self.rules = rules
        self.credential_check = credential_check
        self.depth = depth
        self.count = 0

    def visitnode(self, node):
        self.count += 1
        if self.count > 4096:
            raise Refusal("literal-shell: shell syntax exceeds inspection limit")

    def visitoperator(self, node, operator):
        if operator == "&":
            raise Refusal("no-background: background shell commands are forbidden")

    def visitcommand(self, node, parts):
        for part in parts:
            if part.kind == "assignment":
                _assignment(part.word)
        words = [part for part in parts if part.kind == "word"]
        if not words:
            return
        if words[0].parts:
            raise Refusal("literal-shell: command name must be literal")
        arguments = _unwrap([word.word for word in words])
        if not arguments:
            return
        self._inspect(arguments, words)

    def visitword(self, node, word):
        self.credential_check(word)

    def _inspect(self, arguments, nodes):
        program = arguments[0]
        if program in {"git-send-pack", "git-http-push"}:
            arguments = ["git", program.removeprefix("git-"), *arguments[1:]]
            program = "git"
        if program in {"nohup", "disown", "bg", "setsid", "daemonize"}:
            raise Refusal("no-background: detached processes are forbidden")
        if program in {
            "eval",
            "source",
            ".",
            "sudo",
            "xargs",
            "parallel",
            "alias",
            "unalias",
            "unset",
            "enable",
            "trap",
            "ionice",
            "chrt",
        }:
            raise Refusal("literal-shell: indirect commands cannot be inspected")
        if program == "find" and any(
            word in {"-exec", "-execdir", "-ok", "-okdir"} for word in arguments[1:]
        ):
            raise Refusal("literal-shell: find command execution cannot be inspected")
        if program in {"bash", "sh", "zsh", "dash"}:
            self._shell(arguments)
        elif program in {"git", "gh"}:
            if any(node.parts for node in nodes):
                raise Refusal("literal-shell: Git and PR arguments must be literal")
            if program == "git":
                inspect_git(arguments, self.cwd, self.rules)
            else:
                _pr(arguments)
        check_prefix(arguments, self.rules)

    def _shell(self, arguments):
        if len(arguments) < 3 or arguments[1] not in {"-c", "-lc", "-ec", "-lec"}:
            raise Refusal("literal-shell: only literal shell -c commands can be inspected")
        inspect(arguments[2], self.cwd, self.rules, self.credential_check, self.depth + 1)


def inspect(command, cwd, rules, credential_check, depth=0):
    if depth > 4 or len(command.encode()) > 65_536:
        raise Refusal("literal-shell: command exceeds inspection limit")
    visitor = Inspection(cwd, rules, credential_check, depth)
    try:
        for tree in bashlex.parse(command):
            visitor.visit(tree)
    except (bashlex.errors.ParsingError, NotImplementedError, RecursionError, ValueError) as exc:
        if isinstance(exc, Refusal):
            raise
        raise Refusal("literal-shell: unsupported or malformed shell syntax") from None
