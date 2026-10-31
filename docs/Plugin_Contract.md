# Plugin contract 1.0

The contract is implemented and tested locally but remains provisional before
public distribution. The source of truth is
[`contracts.py`](../packages/devkit/src/devkit/contracts.py); plugin API and
evidence schema versions are independent of distribution versions.

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

Commands use namespaced IDs such as `example.greet`. Each component starts with
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

## Contract tests

[`tests/contract_helpers.py`](../tests/contract_helpers.py) provides an explicitly
authorized temporary service and an assertion that checks both returned data and
persisted evidence. Copy these repository-local helpers with your plugin's tests
until a separate testing distribution is warranted.
[`test_template.py`](../tests/test_template.py) demonstrates their use.

Test each public command with valid input, invalid input, an unmet prerequisite,
and domain failure cases. Test cancellation for handlers that run processes or
perform prolonged work. Inspect `result` and evidence rather than internal helper
call counts. The core suite covers denial, invalid plugin output, registration,
redaction, deadlines, and transport parity. The wheel acceptance script covers
metadata-only discovery and real stdio invocation from independent installations.

`devkit plugins validate` checks activation and environment prerequisites; it
cannot prove a third-party handler's behavior or CLI/MCP equivalence. Keep those
behavioral checks in the plugin's own automated suite.


## Build an independent specialization from the template

The [README whitespace specialization](../examples/readme_specialization.py)
provides a second example with filesystem access, bounded inspection, actionable
failure data, and blocked prerequisites. It depends only on `devkit.contracts`.
To create it outside this checkout:

1. Copy `examples/plugin` to a new directory.
2. Change `devkit-example` to `devkit-textcheck`, `devkit_example` to
   `devkit_textcheck`, and the entry-point name `example` to `textcheck` in
   `pyproject.toml`. Also update the explicit Hatch wheel package path.
3. Rename `src/devkit_example` and replace its `__init__.py` with
   `examples/readme_specialization.py`. Its specialization, command and check IDs
   already use the `textcheck` namespace.
4. Build in that independent directory with `uv build`. Install its wheel with
   the local foundation wheel into an isolated environment. The example does not
   depend on this repository's workspace, test helpers, or optional packages.
5. Select `plugins=["textcheck"]`, trust `devkit-textcheck="0.1.0"` in the external
   policy, and grant `textcheck.readme` with `effects=["read_fs"]` on the desired
   surfaces. Run it against a repository containing a UTF-8 `README.md`.
6. Remove `textcheck` from project selection before uninstalling the wheel.
   Leaving an uninstalled plugin selected produces an explicit activation error;
   it is not silently ignored. Existing evidence remains readable after removal.

[`check_third_party.py`](../scripts/check_third_party.py) performs these steps in
a directory outside the checkout, builds and installs the resulting distribution,
and checks discovery, trust, authorization, successful and failed CLI/Python/MCP
results, persisted evidence, deactivation and uninstall. Another independent
plugin remains usable throughout removal. The full wheel matrix invokes this
acceptance test. This example requires no testing SDK or new plugin abstraction.
