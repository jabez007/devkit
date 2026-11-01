# Author a Devkit specialization

This package checks README files for trailing whitespace without executing project
code. It uses the public Devkit contract and standard Python packaging. Tested
baseline: Linux and Python 3.12. Choose your own package identity before publishing
a derivative. This template is licensed under GPL-3.0-or-later; retain its license
and applicable notices. No installation step grants trust or writes operator policy.

## Create and rename the package

Copy this directory outside the Devkit checkout. Replace `mccann-hub-devkit-example`,
`mccann_hub.devkit_example`, and `example` with your distribution, import package and command
namespace throughout the package, tests, examples and this guide. Rename
`src/mccann_hub/devkit_example` accordingly. Keep the Hatch wheel path and entry-point group
`mccann_hub.devkit.specializations.v1` correct. For example, use distribution
`author-demo-textcheck`, import `author_demo.textcheck`, and command namespace
`textcheck`. Move the implementation to `src/author_demo/textcheck` and set the
Hatch wheel packages to `["src/author_demo"]`.
Choose an import namespace you control and update the Hatch wheel path. Keep the
foundation imports and entry-point group unchanged. The native namespace root
has no `__init__.py`; the leaf plugin package does. GPL terms apply to copied code.

Implement your handler in `src/mccann_hub/devkit_example/__init__.py`. Resolve inputs against
`context.project_root`, declare every effect and surface, return `CommandResult`,
and keep registration free of effects. The example permits only two filenames,
rejects symlinks and special files, and limits inspection to 64 KiB. Its input and
output schemas, `example.readme` command and optional check show the full contract.
Extend `tests/test_plugin.py` for your domain's success, defects and missing
coverage. All test invocations go through `create_service(...).execute(...)`.

## Build, install and test

Obtain a reviewed foundation wheel from your operator. Do not use `pip install
devkit`: the public registry name belongs to a different project. In this package
directory, with `uv` installed, run:

```sh
uv build --out-dir dist
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python /path/to/mccann_hub_devkit-0.2.0-py3-none-any.whl \
  dist/mccann_hub_devkit_example-0.2.0-py3-none-any.whl
uv pip install --python .venv/bin/python 'pytest>=8,<9'
.venv/bin/python -I -m pytest -c pyproject.toml tests
```

Use the actual foundation artifact filename supplied by your operator. Explicit
wheel installation satisfies the plugin's declared foundation dependency without
resolving an unrelated registry package. Runtime dependencies are separate from
the `test` extra. The tests create temporary projects, configuration, grants and
evidence, and never alter your normal operator policy. No Devkit source or
repository-local helpers are required. Build from the sdist as well before release:

```sh
mkdir -p /tmp/mccann-hub-devkit-example-sdist
tar -xzf dist/mccann_hub_devkit_example-0.2.0.tar.gz -C /tmp/mccann-hub-devkit-example-sdist
uv build --wheel /tmp/mccann-hub-devkit-example-sdist/mccann_hub_devkit_example-0.2.0
```

## Select and explicitly authorize

Use a separate target project containing `README.md`. Copy `examples/devkit.toml`
to that project's root. Installation makes metadata discoverable; project
selection requests activation but does not grant trust.

```sh
.venv/bin/devkit --project /absolute/path/to/project plugins
```

An operator reviews the package and merges `examples/policy.toml` into
`$XDG_CONFIG_HOME/devkit/policy.toml`, or `~/.config/devkit/policy.toml` by default.
The policy must be outside the target project, with mode `0600`. Replace the
canonical project path and keep only the required surfaces. A package version
trust entry permits importing code; exact command grants separately authorize
invocation. Prefer a reviewed wheel hash pin for unattended use.

```sh
.venv/bin/devkit --project /absolute/path/to/project doctor
.venv/bin/devkit --project /absolute/path/to/project commands
.venv/bin/devkit --project /absolute/path/to/project --json run example.readme
.venv/bin/devkit --project /absolute/path/to/project check verify
.venv/bin/devkit --project /absolute/path/to/project runs show RUN_UUID
```

The result lists affected line numbers. Fix trailing spaces and rerun. Missing or
unsafe input is blocked; a confirmed whitespace defect fails. `doctor` checks
activation and declared prerequisites, not project correctness.

## Invoke from Python or MCP

Use the same interpreter and operator configuration:

```python
from pathlib import Path
from mccann_hub.devkit.app import create_service

result = create_service(Path('/absolute/path/to/project')).execute(
    'example.readme', {'filename': 'README.md'})
print(result['result'])
print(result['evidence_path'])
```

For MCP, install the reviewed `mccann_hub.devkit_mcp` wheel into this environment and start
`.venv/bin/devkit-mcp --project /absolute/path/to/project`. Connect a standard MCP
stdio client, call `list_tools`, then `call_tool('example.readme', {})`. The tool
returns the same result envelope in structured content, including persisted
evidence. Enable the `mcp` surface explicitly in operator policy. No AI harness
is needed; the [Devkit author guide](https://github.com/jabez007/devkit/blob/main/docs/Plugin_Authoring.md)
includes a complete Python stdio client.

## Deactivate and remove

Remove `example` from the target project's `plugins` list and remove profiles
that reference its checks. Ask the operator to remove its trust and grants if
no other project uses it. Then run:

```sh
uv pip uninstall --python .venv/bin/python mccann-hub-devkit-example
.venv/bin/devkit --project /absolute/path/to/project plugins
.venv/bin/devkit --project /absolute/path/to/project runs show RUN_UUID
```

Historical evidence remains readable. Uninstalling a still-selected plugin causes
an explicit activation error until configuration is corrected. Removal never
rewrites unrelated project settings or deletes evidence.

## License

GNU GPL version 3 or, at your option, any later version published by the Free
Software Foundation (`GPL-3.0-or-later`). See [LICENSE](LICENSE).
