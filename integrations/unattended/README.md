# Guard unattended Claude sessions

This opt-in Linux hook implements the base rules from
[issue #5](https://github.com/jabez007/devkit/issues/5). It consumes Claude Code's
`PreToolUse` JSON on stdin. A refusal returns a synchronous `deny` decision with
the rule identifier. An allowed request produces no output and still goes
through Claude's existing permission checks.

## Install and enable

Install the pinned parser in the interpreter that will run the hook:

```sh
uv pip install --python /absolute/path/to/venv/bin/python \
  -r integrations/unattended/requirements.txt
```

Keep the reviewed assets outside the task worktree. Mount them read-only in a
container. Add the following entry alongside the project's and Gas City's
existing hooks, using absolute paths to that interpreter and the guard:

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/venv/bin/python /absolute/path/to/unattended/guard.py",
        "timeout": 10
      }]
    }]
  }
}
```

Set `DEVKIT_UNATTENDED=1` in the environment that starts Claude. Subagents inherit
that environment. Any set value enables the guard, including an empty string.
When the variable is unset, the hook exits before reading input or rules.
Installing these assets does not register or activate the hook.

## Base rules

| Rule | Refused requests |
|---|---|
| `no-force-push` | Force flags, forced refspecs, mirror pushes and configured mirror remotes. |
| `no-pr-publish` | PR readiness, approval and merge; PR creation without `--draft`; raw `gh api` calls and known GitHub MCP publication tools. |
| `no-protected-push` | Pushes to the remote's locally recorded default branch, `main`, `master`, or configured protected patterns, in any spelling Git resolves to them. Unknown remote defaults, implicit or dynamic destinations and configured push mappings are refused. |
| `no-remote-delete` | Remote deletion flags, deletion refspecs and pruning pushes. |
| `no-background` | Bash background operators, detached launchers and `run_in_background` tool requests. |
| `no-credential-access` | Direct tool access, broad searches, literal shell paths and symlinks to the subscription credential file. `CLAUDE_CONFIG_DIR` is respected. |
| `literal-shell` | Unsupported shell syntax, dynamic program names, dynamic Git/PR arguments, shell aliases, unknown Git commands, changes to the guarded environment and command indirection that the hook cannot inspect. |
| `no-operator-state` | Native `gc` and `bd` commands outside the session list below, closing any bead but the assigned one, Git configuration changes other than `user.name` and `user.email`, and writes under `.git`. |

The shell parser never executes the submitted command. It visits nested command
and process substitutions, pipelines and compound commands. Literal `bash -c`
wrappers and Git aliases are inspected too. The `timeout`, `nice` and `stdbuf`
launchers are normalized before base and stack rules apply. Stack prefixes also
apply to resolved Git aliases. PR review parsing recognizes bundled approval
flags such as `-ab` and skips body, body-file and repository option values.
Other known command indirection, including shell
traps and `find -exec`, is refused. Git queries only read local metadata,
with filesystem monitoring disabled and a two-second timeout. They never contact
a remote. A five-second watchdog returns a refusal before the hook's ten-second
timeout. Invalid input, missing dependencies and invalid rules also refuse the
request without echoing its contents.

A session can read beads with `show`, `list`, `ready`, `search`, `blocked` and
`comments`, and can close the one bead named by `GC_BEAD_ID` in the hook's
environment. It can run `gc base brief lint`, `record`, `show`, `verify` and
`resume`, `gc base feedback questions`, `friction` and `show`, and a stack's
`gc <stack> delivery report`. Everything else, including `brief approve`,
`feedback answers` and `delivery publish`, is refused however the command's
environment is arranged. Without `GC_BEAD_ID` the hook refuses every close.

Use explicit pushes such as `git push origin HEAD:feature-branch`. Prepare the
remote HEAD metadata before the session, and include the actual default and
protected branch names in the reviewed rule file. Protection settings on GitHub
are not discovered by this offline hook. Repository metadata is not a trusted
replacement for that operator-prepared list.

The hook inspects tool requests. It does not sandbox arbitrary programs, test
code, executable replacement or custom MCP implementations. A program the
session writes and runs can still call `gc` or edit Git metadata. Keep assets and
settings read-only, review the tools exposed to the session, and retain the
runtime and remote's independent access controls. In particular, denying a Read
request does not make an authentication file inaccessible to arbitrary code
running under the same operating-system identity.

## Add stack rules

Copy `base-rules.json` to a reviewed rule file. Retain every base rule and value.
Append protected branch patterns or credential paths, or add command prefixes:

```json
"stack.no-publish": {"command_prefix": ["npm", "publish"]}
```

Pass that complete file with `guard.py --rules /absolute/path/to/rules.json`.
Removing a base rule, changing an empty base rule, or removing a protected branch
or credential path refuses every active request. The error names the affected
base rule. New rules can only add denials; they cannot grant a command or override
a base refusal. The loader rejects duplicate keys and rule files over 64 KiB.

The separate Claude skills bundle at `integrations/claude-code` remains unchanged.
The native shared pack layout and runtime installation belong to issue #7.

The [native spike](../../examples/gascity-spike/README.md) runs representative
deterministic guard requests. Its optional live stage verifies force-push and
synthetic credential-read denials in matching Claude tool results, alongside
Gas City's own hooks. It uses subscription authentication and never probes the
real credential file with the agent's tools.

The implementation follows the
[Claude hook contract](https://code.claude.com/docs/en/hooks#pretooluse),
[Git push semantics](https://git-scm.com/docs/git-push), and the non-executing
[bashlex parser](https://github.com/idank/bashlex).
