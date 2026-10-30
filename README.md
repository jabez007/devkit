# Devkit

Composable developer checks, built from scratch. Install the foundation, select
plugins for a project, and authorize their commands through an operator policy.
The CLI, Python API, and optional local MCP server share validation, authorization,
and evidence handling.

The first release provides Go tests and offline Odoo 19 manifest validation.
It needs no Odoo server, Docker, Beads, or model credentials. Package names and
the plugin API remain provisional; these distributions have not been published.

## Set up a development checkout

The tested baseline is Linux, Python 3.12, uv 0.9.5, and Go 1.24.4. Go is needed
only for Go checks. Dependency versions are pinned in [uv.lock](uv.lock).

```sh
uv sync --all-packages --locked
source .venv/bin/activate
devkit --version
devkit --json doctor
devkit plugins
```

Installing a plugin makes it discoverable. It does not activate or authorize it.
`doctor` checks the activated registry and declared environment prerequisites;
with no plugins selected, it checks only the foundation.

To install built distributions in another environment:

```sh
uv build --all-packages
uv venv /tmp/devkit-install --python 3.12
uv pip install --python /tmp/devkit-install/bin/python dist/devkit-0.1.0-py3-none-any.whl
# Add only the plugins and adapters you need:
uv pip install --python /tmp/devkit-install/bin/python dist/devkit_go-0.1.0-py3-none-any.whl
uv pip install --python /tmp/devkit-install/bin/python dist/devkit_odoo-0.1.0-py3-none-any.whl
uv pip install --python /tmp/devkit-install/bin/python dist/devkit_mcp-0.1.0-py3-none-any.whl
```

Use the supplied foundation wheel, since the working distribution name is not an
owned public namespace. The installed-wheel acceptance script constrains registry
dependencies to the lockfile; ordinary wheel installs use the declared ranges.

## Configure a project

Put [examples/devkit.toml](examples/devkit.toml) in the project you want to check.
Keep only the installed plugins and relevant checks. For Odoo alone:

```toml
schema_version = 1
plugins = ["odoo"]
timeout = 90

[options.odoo]
target_version = "19.0"
addons_paths = ["addons"]
strict_dependencies = false

[profiles]
static = ["odoo.manifests"]
```

Settings come from `$XDG_CONFIG_HOME/devkit/settings.toml` (default
`~/.config/devkit/settings.toml`), then the selected project's `devkit.toml`.
Project values replace entire top-level tables; nested tables are not merged.
`--timeout` overrides the configured deadline. Relative addon paths resolve
against `--project`, independent of the caller's working directory. Unknown
settings keys and invalid types fail configuration validation.

## Authorize commands

Create or merge [examples/policy.toml](examples/policy.toml) into
`$XDG_CONFIG_HOME/devkit/policy.toml`, default `~/.config/devkit/policy.toml`.
The policy must be outside the selected project. Set its mode to `0600` and
replace the example project paths with the project's absolute path.

```toml
[trusted_plugins]
devkit-odoo = "0.1.0"

[commands."odoo.module.validate"]
project = "/absolute/path/to/project"
effects = ["read_fs"]
surfaces = ["cli", "python", "mcp"]
```

Trust is bound to the normalized distribution name and exact installed version.
Command grants bind a command to one project, declared effects, and surfaces.
The top-level `deny = ["command.id"]` list overrides grants. Policy is checked
again on each invocation; changing repository settings cannot grant permission.
Only one project grant per command is supported by the current policy format.

Go tests execute repository code and require all five effects: `read_fs`,
`write_fs`, `execute_process`, `network_read`, and `network_write`. Grant MCP
access separately by adding `mcp` to the command's surfaces when needed.
Policy declarations do not sandbox Python plugins or Go tests. Use host isolation
for untrusted code. Package installation itself also lies outside this policy.

## Run and inspect checks

Global flags precede the subcommand:

```sh
devkit --project /absolute/path/to/project plugins validate
devkit --project /absolute/path/to/project commands
devkit --project /absolute/path/to/project --json run odoo.module.validate
devkit --project /absolute/path/to/project --json run odoo.module.validate --args '{"module":"example"}'
devkit --project /absolute/path/to/project --json check static
devkit --project /absolute/path/to/go-project --timeout 120 --json run go.test
```

Go runs `go test -json -count=1 ./...` with the locally installed toolchain,
filtered environment, bounded output, and a shared deadline. Passing, failing,
and skipped tests are counted separately. No executed tests produces `blocked`,
including projects whose tests all skip. No toolchain is downloaded automatically.

Odoo validation parses bounded literal manifests without executing them. It
checks selected field types, the version format, module names, duplicate addons,
and declared data/demo paths. Paths must stay inside the project and module.
Unresolved dependencies are reported; `strict_dependencies=true` makes them
blocking. Success does not establish runtime, database, XML, asset, or external
dependency compatibility. The profile follows [this pinned Odoo 19 source](https://github.com/odoo/odoo/blob/005e0a0eb7ef80cd15b0c82b570b2b0843181ba2/odoo/modules/module.py).

Profiles list check IDs: `go.tests` and `odoo.manifests`. Every required check
must succeed. Child runs have their own evidence and share the profile's deadline
and cancellation signal. An empty profile is blocked; unknown IDs are errors.
Profiles contain at most 128 unique check IDs. Plugin environment checks run
before that plugin's commands and during `doctor`, through the same policy path.

| Result | CLI exit | Meaning |
| --- | --- | --- |
| `success` | 0 | The declared operation completed successfully. |
| `failed` | 1 | An executed check found a problem. |
| `blocked` | 2 | Authorization, a prerequisite, tool, or required coverage is missing. |
| `error` | 3 | Configuration, input, output, execution, deadline, or evidence failed. |
| `cancelled` | 130 | Execution was cancelled. |

`--json` emits one JSON document. Command results contain a stable `reason` code,
domain data, and an `evidence_path`. Read the JSON or evidence for details when a
text summary is insufficient. `plugins` lists installed metadata without imports;
`commands` lists only commands authorized for the CLI. `plugins validate` checks
activation and runs `doctor`; behavioral contract tests run in the test suite.

## Evidence and execution limits

Each invocation writes `$XDG_STATE_HOME/devkit/runs/<uuid>/result.json`, default
`~/.local/state/devkit/runs/<uuid>/result.json`. Run directories use mode `0700`
and results `0600`; writes are atomic. The envelope records arguments, producer
version, timestamps, source revision and dirty state, result, and diagnostics.
Unavailable Git metadata is `null`. Project identity is the SHA-256 of its
resolved local path, so moving the project changes that identity.

Known secret environment values and credential patterns are redacted before
returning or persisting results. Redaction cannot recognize every secret; avoid
putting secrets into command arguments or output. Handler results and arguments
are limited to 1 MiB of JSON; subprocess streams to 256 KiB each; captured Python
diagnostics to 16,384 characters. Arbitrary artifact attachments and automatic
retention are not implemented. The response adds `evidence_path` after writing
the file. An evidence failure returns `EVIDENCE_WRITE_FAILED` and preserves the
actual outcome as `observed_result`, without rerunning the command.

Managed subprocesses are terminated as a Linux process group on timeout or
cancellation. A process that deliberately detaches can escape this mechanism.
Trusted Python handlers must cooperate with cancellation and deadlines; the
runtime cannot forcibly stop arbitrary in-process code. Invocations serialize
Python output capture, and the MCP server handles one tool invocation at a time.
Native file-descriptor writes by plugins are outside Python output capture.

## Python and MCP

```python
from pathlib import Path
from devkit.app import create_service

result = create_service(Path("/absolute/path/to/project")).execute(
    "odoo.module.validate", {"module": "example"}
)
```

For an MCP client's local stdio server configuration, use the absolute path to
`devkit-mcp` in the environment containing the adapter:

```json
{
  "command": "/absolute/path/to/environment/bin/devkit-mcp",
  "args": ["--project", "/absolute/path/to/project"]
}
```

The adapter generates tools from authorized commands and rechecks policy on
calls. It returns the same envelope in structured content. The tested SDK is
MCP 1.30.0 with protocol 2025-11-25. Remote hosting is outside this release.

## Develop a plugin and verify changes

Start from [examples/plugin](examples/plugin), a separate wheel with one command
and one check. See [the plugin guide](docs/Plugin_Contract.md) for the contract,
registration rules, tests, and cancellation requirements.

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run lint-imports
uv run pytest
uv run python scripts/check_wheels.py
```

[CI](.github/workflows/checks.yml) runs these checks on Ubuntu 24.04 using Node 24
action releases. Ruff includes a maximum cyclomatic complexity of 10;
strict typing covers the runtime packages. The wheel matrix builds packages and
tests five fresh environments: foundation, Go, offline Odoo, plugin template,
and combined plugins with MCP. Stdio/process tests require a host runtime that
supports child process communication; they do not complete in this agent's
restricted execution sandbox.

See the [architecture](docs/Composable_Developer_Tookkit_Architecture.md) and
[implementation plan](docs/Implementation_Plan.md) for the fresh-build decisions
and later increments. Live Odoo, Beads, tracker imports, and orchestration remain
future work with separate integration prerequisites.
