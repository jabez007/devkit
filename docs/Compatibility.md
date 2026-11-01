# Compatibility and publication readiness

Status: v0.8 working distributions, reviewed November 1, 2026. Publication is not
part of this milestone. Package names remain provisional.

## Supported public extension points

| Interface | Compatibility commitment |
| --- | --- |
| `devkit.contracts` data classes, status/effect/surface values, specialization API `1.0` | Existing fields and meanings stay compatible within the current contract. Additive fields need defaults; incompatible contract changes require a new API version and entry-point group. |
| `devkit.specializations.v1` registration | Installed metadata is discoverable without importing plugins. Selected code loads only after operator trust checks. |
| `devkit.app.create_service(project, timeout=None)` and returned `.execute(command, arguments, cancellation=...)` | Supported Python invocation entry point. Use keyword arguments for optional behavior. Do not construct the internal service/settings/policy objects. |
| `devkit.processes.run_process` and documented `RunStore` list/show/reference/prune methods | Supported helpers tied to the foundation distribution version; use a minimum dependency matching features used. |
| Result/evidence envelope `1.0` and reference metadata | Existing fields retain meaning. Consumers must tolerate additive fields. Historical evidence stays readable without producing plugins. |
| CLI and optional MCP command invocation | Same command validation, authorization and result semantics. Per-invocation IDs, timestamps and surface metadata differ. Text formatting is for humans; automate against JSON and reason codes. |

Private names, registration internals, policy constructors, configuration loaders,
error prose and service attributes are not extension contracts. The template uses
only the documented interfaces. Its fixture does not depend on internal Devkit
modules or repository tests. A passing conformance test is not a security audit.

A foundation distribution version and plugin API version are different things.
Foundation 0.1.3 adds diagnostic improvements without changing plugin API 1.0.
The example package moves to 0.2.0 because its unpublished greeting command is
replaced by the practical README check. Existing Go, Odoo, Beads and MCP command
contracts remain unchanged.

For changes to documented interfaces in the current 0.1.x line, preserve existing
calls and fields. Before an incompatible change, document the replacement,
affected versions and migration steps in the implementation plan and release
notes. Prefer one documented compatible release before removal; do not invent a
fixed calendar support period before a release process exists. Security fixes
may need an explicitly documented exception. Any future contract 2.0 requires
separate registration compatibility tests rather than silent interpretation as 1.0.

## Python and dependencies

The qualified baseline is Linux with CPython 3.12, as exercised in hosted CI.
`Requires-Python >=3.12` permits newer Python versions but does not certify them.
Other Python versions and operating systems remain unqualified. The process
supervisor, evidence locking and template file-safety checks use Linux facilities.
No AI harness, Docker, Beads or Odoo is required by the foundation.

Runtime dependency ranges are declared in each distribution's `pyproject.toml`.
The repository's `uv.lock` defines the exact development/acceptance versions.
Ordinary installs resolve declared ranges; the tested lockfile does not prove
that every allowed dependency version works. A lower-bound/newer-Python matrix is
a useful next release prerequisite. Authors using the current context, process
and evidence helpers should require `devkit>=0.1.2,<0.2`; older packages retain
their existing ranges. Template pytest is an optional development extra only.

Use explicit reviewed foundation and specialization wheels together. Do not let
a plugin's provisional `devkit` dependency resolve to a public package with the
same name. The root package includes `py.typed`; installed consumer acceptance
checks the contract annotations with strict mypy. This does not make all internal
implementation modules supported extension points.

## Owner decisions before publication

The following read-only registry checks were performed on November 1, 2026:

- [`devkit`](https://pypi.org/project/devkit/) already exists on PyPI as a different
  project, version 0.0.12. Do not publish or install this repository under that
  registry name without a separately approved naming plan.
- JSON endpoints for `devkit-go`, `devkit-odoo`, `devkit-beads`, `devkit-mcp` and
  `jabez-devkit` returned 404. Absence is a time-specific observation, not a
  reservation, ownership claim or guarantee of future availability.
- GitHub reports `jabez007` as repository owner and no detected license. No license
  file is currently supplied. Public source access does not grant redistribution
  rights. No legal license was selected in this milestone.

Recommended decisions, requiring owner approval:

1. Choose an owned distribution family, for example `jabez-devkit` and matching
   specialization names. Before applying it, decide import and CLI names too;
   retaining `devkit` imports would still conflict with an unrelated package using
   that module. Rename dependency declarations, entry-point distributions, trust
   examples and artifact acceptance together. Test old/new coexistence or explicitly
   reject it. No namespace is claimed by these recommendations.
2. Choose a license. Apache-2.0 is a candidate when an explicit patent grant is
   wanted; MIT is a shorter permissive alternative. Have the owner confirm rights
   to all shipped code. Then add the approved license text, SPDX metadata and
   required notices to every wheel/sdist, including the reusable template.
3. Approve release ownership and provenance. Set the registry organization/account,
   protected release workflow and signing/attestation policy. Build from an approved
   tag in CI, run the entire acceptance matrix, record wheel hashes and publish
   only reviewed artifacts. Configure trusted publishing rather than embedding
   long-lived tokens. No release or registry publishing workflow is enabled here.

Locally completed preparation includes package descriptions and READMEs, source
URLs, independent wheel/sdist builds, installed type markers, template-owned tests,
sdist rebuild acceptance and package-content validation. Metadata intentionally
omits a license until the owner chooses one. No public release or namespace claim
is needed to reproduce the authoring workflow with reviewed local artifacts.

## Trust and provenance limits

Installation, selection, trust and command grants are separate. Version trust
checks distribution metadata; it is not executable identity. Existing optional
wheel pins verify archive SHA-256 and installed payload before activation. Keep
pins outside repositories and renew them for changed artifacts. They do not prove
publisher identity, inspect transitive dependencies, or sandbox Python imports.
Build systems and packages can execute code; run unknown builds in an isolated
host environment. Installation must never grant permissions or alter policy.

`plugins list --details` reports configured selection and trust only. It does not
import plugins or verify wheel pins. `plugins validate` attempts activation and
prerequisite checks through the existing service, where pins are enforced.
