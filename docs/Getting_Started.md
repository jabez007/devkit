# Start using Devkit

Choose the path matching your role. The qualified baseline is Linux and Python
3.12. Devkit works from a shell or editor terminal without any AI harness. Public
package names are provisional: obtain reviewed wheel artifacts from your operator,
not the unrelated PyPI `devkit` package.

## Developer: verify a project

Create an environment and install the foundation plus a specialization. This
example uses the supplied README check, which needs no Go, Odoo or Beads:

```sh
uv venv /tmp/devkit-user --python 3.12
uv pip install --python /tmp/devkit-user/bin/python \
  /path/to/wheels/devkit-0.1.3-py3-none-any.whl \
  /path/to/wheels/devkit_example-0.2.0-py3-none-any.whl
/tmp/devkit-user/bin/devkit plugins
```

Installation makes the package discoverable. Put this in the target project's
`devkit.toml`, alongside its `README.md`:

```toml
plugins = ["example"]
[profiles]
verify = ["example.readme"]
```

The operator must explicitly trust and authorize the package as described below.
Then run:

```sh
/tmp/devkit-user/bin/devkit --project /absolute/path/to/project plugins list --details
/tmp/devkit-user/bin/devkit --project /absolute/path/to/project plugins validate
/tmp/devkit-user/bin/devkit --project /absolute/path/to/project commands
/tmp/devkit-user/bin/devkit --project /absolute/path/to/project --json check verify
```

`commands` lists commands authorized for the CLI. `plugins validate` and `doctor`
check activation and prerequisites, not project correctness. `check verify`
examines README whitespace and records evidence. Failed results identify defects;
blocked results identify unavailable coverage or authorization. Use `runs show
RUN_UUID` with the same `--project` to retrieve the result. Parent checks include
child evidence links. `runs list --reference STRING` finds explicitly associated
runs and needs no plugin.

Always pass the project root from an editor terminal in a subdirectory. Devkit
does not search ancestors for configuration or replace a linked checkout with its
main checkout. To remove a plugin, remove its selection and affected check profile
entries before uninstalling its distribution. Historical evidence remains readable.

## Operator: review trust and grant only needed capabilities

Review the source, wheel, dependency versions and declared effects before trusting
a plugin. Importing trusted Python code can have effects outside command handling.
Policy is not a filesystem or network sandbox. Keep builds of unknown code in
host isolation and prefer the existing artifact pin mechanism for unattended use.

Merge this example into `$XDG_CONFIG_HOME/devkit/policy.toml`, defaulting to
`~/.config/devkit/policy.toml`. Keep it outside the target project and mode `0600`.
Replace the canonical project path. Do not overwrite unrelated grants:

```toml
[trusted_plugins]
devkit-example = "0.2.0"

[commands."example.readme"]
project = "/absolute/path/to/project"
effects = ["read_fs"]
surfaces = ["cli", "python"]
```

This version trust permits activation; the exact command grant permits invocation.
Add `mcp` only when the optional adapter is wanted. For several projects, reuse
existing operator profiles with explicit project paths. No plugin installation
writes this file. See [artifact pins and policy profiles](../README.md#authorize-commands)
for the stronger wheel-payload check and existing grant syntax.

Inspect configured state with `plugins list --details`. It reports selection,
missing distributions, configured trust and the policy path without importing
plugins. A `wheel-pin-unverified` label means the pin is configured, not verified.
Run `plugins validate` to perform activation and enforce artifact pins. Successful
validation does not grant any missing command permission or certify arbitrary code.

| Diagnostic | Correction |
| --- | --- |
| `PLUGIN_SELECTION` | Install the selected distribution, remove a stale selection, or resolve duplicate entry-point IDs. |
| `UNTRUSTED_PLUGIN` | Review the installed distribution/version and update external trust explicitly. |
| `ARTIFACT_MISMATCH` | Check the reviewed wheel hash and installed payload; do not bypass a failed pin. |
| `DENIED` | Check command ID, canonical project path, effects, surface, explicit denies and revoked trust in `policy.toml`. |
| `INVALID_CONFIG` / `INVALID_POLICY` | Correct the named settings file or policy schema, path and permissions. Default `plugins list` still works with broken project settings. |
| `PREREQUISITE_FAILED` | Read the child check diagnostic and its evidence. Install/configure only the required prerequisite. |

## Plugin author: distribute a capability

Copy the [standalone template](../examples/plugin), rename its package/namespace,
implement a command and adapt its installed-package tests. Follow the
[authoring guide](Plugin_Authoring.md) for the public Python interface, conformance
coverage and a complete MCP client. The template README contains the full
build/install/authorize/remove procedure and example TOML files.

You do not need Devkit's source tree, internal service constructors or test helpers.
No testing SDK is currently needed. Review the [compatibility and publication
policy](Compatibility.md) before declaring support or releasing a package.
