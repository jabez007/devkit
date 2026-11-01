# Plugin contract 1.0

The contract is implemented and tested locally but remains provisional before
public distribution. The source of truth is
[`contracts.py`](../packages/devkit/src/devkit/contracts.py); plugin API and
evidence schema versions are independent of distribution versions.
The foundation wheel includes a `py.typed` marker for its inline annotations.
Installed-consumer acceptance checks valid and invalid `CommandResult` statuses
with strict mypy. This does not promise stability for every internal module;
plugin authors should use the contracts documented here.

## Package and register

Copy [the example package](../examples/plugin). Rename its distribution, import
package, entry-point name, and command namespace together. Build it with
`uv build examples/plugin` from the repository root. Install it alongside the
local foundation wheel; do not resolve the provisional foundation name from a
public registry. Repository tests build and install the example independently.

```toml
[project.entry-points."devkit.specializations.v1"]
example = "devkit_example:register"
```

`register()` returns a `Specialization` with its entry-point ID, commands, and
optional checks/environment checks. It takes no arguments. Registration and
module import must not print, inspect projects, start processes, or perform
network operations. Installed metadata is discoverable without importing the
plugin. Activation first checks the entire selection for missing, duplicate, or
untrusted distributions, then imports only selected, explicitly trusted versions.
An optional operator wheel pin additionally verifies the archive SHA-256 and
installed payload before registration. Pins require a normal wheel installation;
editable development checkouts must use version-only trust. See the
[trust configuration and limits](../README.md#authorize-commands).

Commands use namespaced IDs such as `example.readme`. Each component starts with
a lowercase letter and contains lowercase letters, digits, or underscores.
Commands and checks stay inside the plugin's namespace. Duplicate IDs,
unsupported API versions, invalid schemas, and unknown effects/surfaces fail
activation. All check references point to commands declared by the same plugin;
their fixed arguments must satisfy the referenced command's input schema.

## Commands and results

A `CommandSpec` supplies `id`, `description`, and
`handler(context, arguments) -> CommandResult`, with these optional fields:

| Field | Contract |
| --- | --- |
| `input_schema` | Draft 2020-12 object schema; default accepts only an empty object. |
| `output_schema` | Draft 2020-12 object schema for successful `data`; default accepts any object. |
| `effects` | Subset of `read_fs`, `write_fs`, `execute_process`, `network_read`, `network_write`. |
| `surfaces` | Subset of `cli`, `python`, `mcp`; defaults to all three, still requiring operator grants. |

Schemas must be self-contained. Local fragment references are allowed; external
references and `$id` are rejected. Input and output use JSON-native values,
including string dictionary keys and arrays as lists. Bytes, tuples, non-finite
numbers, and arbitrary Python objects are invalid. Each input and handler result
is limited to 1 MiB of serialized JSON.

`CommandResult` contains `status`, `summary`, `data` (an object), and optional
`reason`. Status is `success`, `failed`, `blocked`, `error`, or `cancelled`.
Summaries are at most 4,096 characters. Every result is checked against the
shared result schema; successful data is also checked against `output_schema`.
Failures may use diagnostic data that does not match the success schema.
Use stable machine-readable reason codes and avoid secret values in summaries.

Context supplies the resolved `project_root`, `run_id`, monotonic `deadline`,
threading `cancellation` event, plugin options under `settings[plugin_id]`, and
invocation `surface`. Treat it as supplied context; do not resolve configuration
again or call a command handler directly. The service owns validation, policy,
prerequisites, diagnostics, and evidence.

Python handlers must check cancellation and deadlines around bounded work.
Foundation 0.1.2 adds optional `Context.state_root`, the resolved local evidence
store. The invocation service always supplies it; manually constructed contexts
may omit it. Existing positional construction and plugin API 1.0 remain valid.
Use `RunStore(context.state_root)` for evidence references, rather than resolving
global configuration again.

`devkit.processes.run_process(argv, context, environment=None)` provides bounded
capture, deadline enforcement and process-group cancellation on Linux. An explicit
string mapping replaces the inherited environment completely; omit it to retain
the existing filtered Go-compatible defaults. Plugins using these additions must
require `devkit>=0.1.2,<0.2`. This helper follows the foundation package version,
not a separate protocol version.
Long-lived or untrusted work needs host isolation. Declared effects are policy
inputs, not interception of Python filesystem or network calls.

## Checks and prerequisites

`CheckSpec(id, command, arguments={})` references a command. Project profiles
select check IDs. Environment checks are prerequisites for that plugin's other
commands and for `core.doctor`; environment-check commands do not recursively run
the same prerequisites. Every child execution receives independent authorization
and evidence, an inherited deadline and cancellation signal, and a parent run ID.

Aggregates succeed only if all children succeed. Mixed results use this priority:
`cancelled`, `error`, `failed`, `blocked`, `success`. Empty profiles are blocked.
A failed prerequisite blocks its parent handler. Error/cancelled prerequisites
preserve that status. The first implementation does not cache prerequisites or
offer arbitrary dependency graphs between checks.

## Test an independent plugin

The [template tests](../examples/plugin/tests/test_plugin.py) are self-contained.
Install your built wheel and pytest, then run them outside this repository with
`python -I -m pytest -c pyproject.toml tests`. They write temporary project and
operator configuration and call the public `devkit.app.create_service` entry
point. They do not construct internal settings/policy objects or import Devkit's
repository-local helpers. No testing SDK or runtime pytest dependency is needed.

The template covers installed registration, a configured check, valid and invalid
input, domain failure, unsafe files, denial, a failed prerequisite, handler errors,
invalid output, cancellation and persisted evidence. Adapt its domain assertions
when implementing your command. The [authoring guide](Plugin_Authoring.md) maps
other foundation conformance coverage and documents deadline testing. Passing
these tests does not certify arbitrary plugin code as safe.

`devkit plugins validate` checks activation and environment prerequisites through
`doctor`. It cannot prove a handler's behavior or transport equivalence. Registry
validation includes API versions, namespaced IDs, schemas, effects and surfaces.
The core tests remain authoritative for these generic rejection rules rather than
copying their entire suite into every external package.

## Build an independent specialization from the template

The [template package](../examples/plugin) now contains the bounded README check,
project/policy examples, tests and its own author guide. It supersedes the separate
`examples/readme_specialization.py` implementation and the greeting-only template.
The unpublished example distribution is version 0.2.0; the public plugin contract
is still 1.0. Rename the distribution, import package, entry point, command/check
namespace, tests and example configuration together.

[`check_third_party.py`](../scripts/check_third_party.py) copies and renames this
complete package outside the checkout, builds its sdist and rebuilds a wheel from
that sdist. It installs only wheels, runs the package's own tests with isolated
Python, checks import origins and proves that metadata discovery and untrusted
selection do not import plugin code. CLI/Python/MCP success, defect, invalid-input
and denial results match. Deactivation and uninstall leave an unrelated plugin
and historical evidence usable. The full wheel matrix runs this workflow.
