# Use Devkit in Claude Code

This optional plugin adds two skills for verification evidence and Beads work
items. It uses the existing `devkit` CLI and optionally `devkit-mcp`. It contains no
hooks, agents, automatic grants, MCP startup, or task scheduler. The standalone
directory is licensed under [GPL-3.0-or-later](LICENSE).

## Install and load

Use Linux with Python 3.12. Obtain reviewed wheels and this plugin directory from
your operator. Follow the [Devkit onboarding guide](https://github.com/jabez007/devkit/blob/main/docs/Getting_Started.md)
to install the foundation and desired specialization into a Python environment.
The distribution family is `mccann-hub-devkit`; the PyPI `devkit` package is unrelated.
For example, install a reviewed Go wheel alongside the foundation:

```sh
uv venv /tmp/devkit-user --python 3.12
uv pip install --python /tmp/devkit-user/bin/python \
  /path/to/wheels/mccann_hub_devkit-0.2.0-py3-none-any.whl \
  /path/to/wheels/mccann_hub_devkit_go-0.1.0-py3-none-any.whl
export PATH="/tmp/devkit-user/bin:$PATH"
devkit --version
```

Select `go` in your project's `devkit.toml` and define a verification profile:

```toml
plugins = ["go"]
[profiles]
verify = ["go.tests"]
```

Have the operator review package trust and authorize the command for the canonical
checkout path. This example is a deliberate operator edit to the external
`$XDG_CONFIG_HOME/devkit/policy.toml`, defaulting to `~/.config/devkit/policy.toml`.
Merge it without overwriting other grants and keep the file mode `0600`:

```toml
[trusted_plugins]
mccann-hub-devkit-go = "0.1.0"

[commands."go.test"]
project = "/absolute/development/checkout"
effects = ["read_fs", "write_fs", "execute_process", "network_read", "network_write"]
surfaces = ["cli", "python"]
```

Use the existing wheel-payload pins for stronger artifact identity checks. Installing
either the Python distribution or Claude plugin does not activate or authorize it.
Trusted Python code and repository tests can execute arbitrary code; Devkit policy
is not process isolation. Claude's tool permissions remain separate.

Copy the complete `claude-code` directory to a reviewed location, including hidden
`.claude-plugin`, references, helper, and license. Start Claude in the development
checkout, not in the plugin directory:

```sh
cd /absolute/development/checkout
claude --plugin-dir /absolute/reviewed/claude-code
```

Invoke `/mccann-hub-devkit:devkit-verification` and request the configured `verify`
profile. The skill resolves the checkout, inspects discovery and prerequisites,
and uses `devkit --project /absolute/development/checkout --json check verify`.
Follow evidence with `devkit --project /absolute/development/checkout --json runs
show RUN_UUID`. Preserve nonzero results and their diagnostics.

For a monorepo subproject or non-Git directory, explicitly name the desired project.
Automatic selection uses the current Git worktree root. A linked worktree requires
its own operator scope and retains separate evidence. It never inherits the main
checkout's grants simply because it shares Git objects or a Beads ledger.

Neovim needs no integration package. Use the same commands from its terminal and
start a native Claude session there if desired. All Devkit commands remain usable
without Claude, Beads, or Odoo installed.

## Enable optional MCP

CLI use needs no MCP package. To enable MCP, install the reviewed
`mccann-hub-devkit-mcp` wheel into the same environment and explicitly add `mcp` to
the desired command grants. From the selected checkout, register the existing
server with fixed absolute paths:

```sh
cd /absolute/development/checkout
claude mcp add --transport stdio --scope local devkit -- \
  /tmp/devkit-user/bin/devkit-mcp --project /absolute/development/checkout
```

Check `/mcp` in Claude and compare the configured project path with the active
checkout before invocation. Local scope is private to this project. Repeat setup
for a different worktree, or use CLI there. Do not register this fixed binding at
user scope or use the plugin installation directory as its project. A missing
adapter or mismatched binding is a reason to use CLI, not to start another server.
Remove this optional binding from its project with `claude mcp remove --scope local
devkit` when no longer wanted. Plugin removal alone does not remove an independently
configured server.

## Use an optional Beads task

Install the reviewed `mccann-hub-devkit-beads` wheel and supported Beads 1.3.2 CLI.
Select `beads` alongside existing plugins. Use an already initialized workspace and
the [Beads policy examples](https://github.com/jabez007/devkit/blob/main/docs/Beads_Integration.md) for explicitly chosen
read, association, or lifecycle commands. Restricted read operation remains valid.

Invoke `/mccann-hub-devkit:devkit-work-items`. Select a returned qualified item ref,
inspect its description and blockers, and request only the intended actions. For
example, ask to claim that item with an operator-chosen actor label, make a scoped
code change, verify it, and associate the resulting run. Review results before
requesting a comment or closure. A passing check alone does neither. The
[work-item reference](references/work-items.md) documents commands and recovery.

## Diagnose or remove

| Symptom | Next step |
| --- | --- |
| `devkit` missing | Activate the reviewed Python environment or use its absolute executable. |
| Selected plugin missing/untrusted | Inspect `plugins list --details`, then `plugins validate`; request installation or operator trust review. |
| `DENIED` | Read the named project/effects/surface requirement; do not broaden policy automatically. |
| Doctor succeeds but no project checks ran | Select a configured verification profile; doctor checks prerequisites. |
| Invalid profile | Inspect `[profiles]` in project and user settings; project tables replace matching user tables. |
| Odoo incomplete dependencies | Report unknown coverage; strict mode blocks rather than declaring missing dependencies. |
| MCP absent or wrong checkout | Use CLI with explicit `--project`; correct the local MCP binding separately. |
| Association failed | Inspect the item and run in the same checkout; reconcile references before retrying that pair. |
| Beads mutation outcome uncertain | Inspect native state; do not replay writes automatically. |
| Evidence not found | Use the original checkout and run UUID; do not substitute another worktree. |

For `--plugin-dir` loading, quit Claude and restart without that flag to remove the
integration. If installed by another supported native mechanism, disable or remove
it using Claude's plugin controls. Devkit's configuration, packages, references,
and evidence remain independent. Verify with `devkit --project /original/checkout
--json runs show RUN_UUID` after removal.

## Compatibility and qualification

Plugin version 0.1.0 targets foundation 0.2.0, specialization API 1.0, and evidence
envelope 1.0. No Python plugin contract changes are required. The plugin's own
version is independent of foundation releases. See the repository's
[compatibility policy](https://github.com/jabez007/devkit/blob/main/docs/Compatibility.md) and
[implementation plan](https://github.com/jabez007/devkit/blob/main/docs/Implementation_Plan.md) for qualification results.

The native conventions were reviewed against official Claude documentation:
[plugin loading](https://code.claude.com/docs/en/plugins),
[skills and tool permissions](https://code.claude.com/docs/en/skills), and
[project-local MCP setup](https://code.claude.com/docs/en/mcp).
The bundle deliberately omits `allowed-tools` preapprovals and bundled MCP startup.
Skills guide a model; deterministic tests cannot prove it will follow every
instruction. Live qualification must be reported separately from direct CLI tests.

## Reproduce acceptance

From a Devkit source checkout with its development environment installed, run the
focused checks and the complete installed-wheel matrix. The matrix builds wheels
and tests the copied plugin procedures in temporary directories outside the repo:

```sh
uv run pytest -q tests/test_claude_integration.py
uv run mypy --strict integrations/claude-code/scripts/checkout.py
DEVKIT_BEADS_BINARY=/absolute/path/to/bd-1.3.2/bd \
  uv run python scripts/check_wheels.py
```

For native plugin checks, use a disposable Claude configuration directory:

```sh
export CLAUDE_CONFIG_DIR="$(mktemp -d /tmp/devkit-claude-config.XXXXXX)"
claude plugin validate --strict /absolute/reviewed/claude-code
claude --plugin-dir /absolute/reviewed/claude-code plugin details mccann-hub-devkit
claude --plugin-dir /absolute/reviewed/claude-code plugin disable mccann-hub-devkit@inline
claude --plugin-dir /absolute/reviewed/claude-code plugin list --json
claude --plugin-dir /absolute/reviewed/claude-code plugin enable mccann-hub-devkit@inline
claude plugin list --json
```

The disabled listing should report `enabled: false`; the final session without
`--plugin-dir` should list no plugin in this otherwise empty profile. These commands
were exercised with Claude Code 2.1.316. They do not start a model session.

For an opt-in model exercise, build reviewed wheels and export pinned dependency
constraints from the lockfile, then choose a new temporary output directory:

```sh
uv build --all-packages --out-dir /tmp/devkit-v09-wheels
uv export --all-packages --no-dev --no-emit-workspace --no-hashes \
  --format requirements-txt --output-file /tmp/devkit-v09-constraints.txt
DEVKIT_BEADS_BINARY=/absolute/path/to/bd-1.3.2/bd \
  uv run python scripts/check_claude_live.py \
  /tmp/devkit-v09-live-new /tmp/devkit-v09-wheels \
  /tmp/devkit-v09-constraints.txt /absolute/path/to/claude
```

This opt-in script uses an authenticated API environment, may incur model charges,
and limits each session to $5. It loads only the copied plugin, uses separate
temporary Claude configuration, disables MCP for CLI qualification, grants only
the fixture's Devkit/helper shell commands and file/skill tools, and preserves
permission denials as test failures. It does not load personal hooks or persist
Claude sessions. It checks actual source, Beads state, associations, and evidence
after the model exits; a plausible narrative alone cannot pass. Fixture policy
generation belongs to the test harness, never the shipped plugin's setup.

On November 1, 2026, native loading and deterministic workflows passed. The model
request returned `Credit balance is too low` before any task action. Model-driven
Go/Odoo qualification remains open; the script is provided for a funded test
environment. The implementation plan records the full gate results and scope.
