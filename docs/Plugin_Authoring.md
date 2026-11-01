# Create and test a specialization

Start with the [self-contained template](../examples/plugin). Its README covers
renaming, implementation, tests, wheel and sdist builds, configuration, trust,
CLI/Python invocation and removal. Copy that directory outside Devkit. You need
reviewed foundation artifacts and ordinary Python packaging tools, not this
repository's implementation or test helpers.

## Keep the public interface small

Import the data contracts from `mccann_hub.devkit.contracts`. Registration returns a
`Specialization` through the `mccann_hub.devkit.specializations.v1` entry point. In tests and
Python consumers, use `mccann_hub.devkit.app.create_service(Path(project), timeout=...)`
and its returned service's `execute(command, arguments, cancellation=...)` method.
Do not call handlers directly for integration tests or construct the internal
service settings/policy objects. An isolated test policy is an explicit fixture,
not a permission grant to install into a user's environment.

Use `mccann_hub.devkit.processes.run_process` for supervised subprocesses if your command
needs them. The README example needs no subprocess. Check cancellation/deadlines
around long work; synchronous Python handlers cannot be forcibly interrupted.
Effects describe capabilities for policy review, not a sandbox for arbitrary code.

Every handler returns `CommandResult`, never a complete evidence envelope. The
service validates arguments/results and supplies run identity, timestamps and
persisted evidence. Include actionable defects in failed results and explain
missing coverage in blocked results. Schemas constrain inputs before execution.
Choose explicit command namespaces, effects and surfaces. Declare a `CheckSpec`
when the command makes sense in a verification profile.

## Run your tests against installed artifacts

The template's tests use only your installed package, public Devkit interfaces,
stdlib and pytest. They run with temporary configuration/state roots. Installation
and tests must not write to the operator's normal policy file. Build both formats,
rebuild the wheel from the sdist, then follow the template's install/test commands.
Run from outside the Devkit checkout without `PYTHONPATH`. `python -I` removes
ambient Python path injection. Verify imported package files live in the chosen
virtual environment, not an editable checkout.

The authoritative generic conformance tests remain in Devkit. Do not copy a
complete duplicate suite into each plugin:

| Behavior | Existing evidence / author responsibility |
| --- | --- |
| Valid registration and optional check | Template-owned installed tests and `plugins validate` |
| Unsupported API version, invalid namespace/IDs, duplicate IDs | Foundation `test_plugins.py`; activation and service construction reject these |
| Invalid input/output schemas, unknown effects/surfaces | Foundation `test_plugins.py`; declare only documented values |
| Invalid input, output, handler exceptions, denial | Template tests exercise the public service; foundation tests cover malformed/non-JSON envelopes |
| Failed prerequisites | Template fixture demonstrates a declared environment check and its separately granted command |
| Cancellation | Template tests pre-cancelled invocation; test active cancellation if your command performs prolonged work |
| Deadlines and process cancellation | Foundation `test_processes.py` and `test_foundation.py`; subprocess authors should test their own tool's timeout and cleanup behavior |
| Persisted evidence | Every template invocation compares returned and stored results and run/project identities |
| CLI/Python/MCP equivalence | Independent wheel acceptance runs success, defect, invalid input and denial scenarios |
| Deactivation/removal | Independent acceptance retains unrelated plugins and historical evidence |

These tests establish the behavior exercised, not that a plugin is safe or secure.
A reviewed artifact, trusted dependency chain and appropriate host isolation are
still needed. No external testing SDK is necessary for the current template.

## Exercise MCP without an agent harness

Install the reviewed foundation, plugin and `mccann-hub-devkit-mcp` wheels together. Grant
the same command on the `mcp` surface. The MCP adapter brings its client library
and AnyIO dependencies. Save this as `mcp_check.py` and run it with that environment's
Python, passing the absolute project path:

```python
import json
import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mccann_hub.devkit.app import create_service

async def main():
    project = Path(sys.argv[1]).resolve()
    expected = create_service(project).execute('example.readme', {})['result']
    params = StdioServerParameters(
        command=str(Path(sys.executable).with_name('devkit-mcp')),
        args=['--project', str(project)], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print([tool.name for tool in (await session.list_tools()).tools])
            response = await session.call_tool('example.readme', {})
            envelope = response.structuredContent
            assert envelope['result'] == expected
            stored = json.loads(Path(envelope['evidence_path']).read_text())
            assert stored['result'] == expected
            print(envelope['evidence_path'])

anyio.run(main)
```

Run with `python mcp_check.py /absolute/path/to/project`. The independent acceptance
script executes this same stdio-client procedure against the renamed plugin,
including invalid and denied calls. Compare `result`, not complete envelopes:
run IDs, source surfaces and timestamps legitimately differ between invocations.

## Reproduce the clean-room acceptance

Maintainers can run `uv run python scripts/check_wheels.py` with
`DEVKIT_BEADS_BINARY` pointing to the pinned Beads 1.3.2 binary. This includes the
third-party exercise and existing domain regressions. To run only the authoring
exercise, build the foundation, MCP and example wheels, prepare constraints from
`uv.lock`, then run:

```sh
.venv/bin/python scripts/check_third_party.py \
  /tmp/new-devkit-author-run /absolute/path/to/wheels /absolute/path/to/constraints.txt
```

The destination must not exist. The harness copies only the template into the
author workspace. It renames the package, rebuilds from sdist, installs wheels,
runs the template's own tests under isolated Python, checks import origins and
exercises discovery, explicit activation/trust/grants, all transports and removal.
An import marker added only to this acceptance copy proves that build, metadata
discovery and untrusted selection do not execute it. The marker is not part of
the supplied template or a recommended plugin behavior.

For supported extension points, dependency ranges and publication blockers, read
[compatibility and publication readiness](Compatibility.md).
