# Devkit implementation plan

Status: First-release implementation complete; public publication is pending.\
Date: October 30, 2026.\
Scope: Build a new toolkit inspired by Crpaxton4/devcontainer-features.\
First release: Go checks and offline Odoo validation, as selected by the project owner.

## Delivery progress

| Slice | State | Verification |
| --- | --- | --- |
| 0 | Complete | Five tests, lint including complexity, formatting, strict typing, import contract, and isolated foundation wheel installation passed. Python 3.12 and Linux are the initial baseline. |
| 1 | Complete | Ten tests and all configured checks passed. An independently installed fixture wheel proved metadata-only discovery, blocked untrusted imports, and authorized invocation. |
| 2 | Complete | Seventeen tests passed, including real Go pass/fail/skip cases and process-group timeout, cancellation, bounded output, and environment filtering. Go 1.24.4 was tested. |
| 3 | Complete | Twenty-eight tests and all configured checks passed. Installed-wheel validation ran without Odoo, Docker, or MCP. Manifest rules were checked against Odoo revision `005e0a0eb7ef80cd15b0c82b570b2b0843181ba2`. |
| 4 | Complete | Thirty tests passed, including real stdio discovery, three-interface parity, denial, revocation, and cancellation of a running Go test. MCP SDK 1.30.0 negotiated protocol 2025-11-25. Stdio tests require the host runtime in this sandbox environment. |
| 5 | Complete | Forty-three tests and five independent wheel environments passed. Includes profiles, prerequisite checks, plugin template, contract helpers, documentation, strict JSON results, bounded diagnostics, and Git metadata hook suppression. |

Build a small Python foundation that discovers explicitly activated plugins, invokes commands through one policy path, and produces portable evidence. Prove the design with useful Go checks and Odoo manifest validation before adding live Odoo environments, task connectors, or orchestration.

The [architecture draft](Composable_Developer_Tookkit_Architecture.md) defines the responsibilities and fresh-build scope. This plan supplies the delivery slices and acceptance gates. Compatibility with upstream commands, databases, package names, and deployment workflows is outside scope.

## Architecture review

The strongest decisions are the separation of development capabilities from work tracking, optional integrations, standard plugin packaging, and one invocation implementation across interfaces. Keep them. Upstream [ADR-006](https://github.com/Crpaxton4/devcontainer-features/blob/main/docs/design/adr/ADR-006-workspace-three-layers-state-root.md) describes a shared command registry and enforced package dependencies. Those are useful design precedents for this project.

Architecture draft 0.3 records the implemented first release. The original review findings and their disposition are retained below. References identify sections in the architecture.

| Priority | Original finding and consequence | Disposition |
| --- | --- | --- |
| High | Settings precedence could be confused with authorization; the MCP example lacked trusted grants. | Implemented external operator policy, exact distribution-version trust before imports, project-bound command grants, and explicit denial precedence. |
| High | Output schemas, checks, handler context, and statuses were undefined. | Implemented and documented the shared result, command, check, context, and aggregation contracts. |
| High | Cancellation had no enforcement semantics. | Cooperative Python cancellation and supervised Linux process-group termination are implemented and tested; limitations are documented. |
| Medium | Identity, source state, evidence failures, and absent coverage were underspecified. | Implemented path-hash project identity, Git revision/dirty state, atomic evidence with explicit storage failures, and blocked empty verification. Arbitrary artifacts are deferred. |
| Medium | Section 8.3 requires idempotent imports but does not define recovery after Beads creation succeeds and the connector checkpoint fails. | Before shipping the connector, prove lookup or reconciliation using a stable external key. Block ambiguous retries rather than creating another issue. |

Section 8.2's Beads deployment assumptions also need validation against a selected release. Treat embedded and server modes as candidates until integration tests establish the supported configuration. This does not block the first release.

The architecture now uses implemented configuration and result examples and omits upstream SDK dependencies and migration obligations. The plugin interface remains provisional until a public compatibility commitment is made.

## First release scope

The release must support these workflows:

- Install the foundation alone and run `doctor`, plugin discovery, and command discovery without Go, Odoo, Beads, Docker, or an agent harness.
- Install and activate the Go plugin, run tests in a selected project, and receive validated results and evidence.
- Install and activate the Odoo plugin, validate addon manifests and declared local files without importing Odoo or executing manifest code.
- Activate both plugins in one project without namespace conflicts or special cases in the foundation.
- Invoke an allowed command through Python, the CLI, and an optional local stdio MCP adapter with equivalent argument validation, policy decisions, and result meaning.
- Receive an honest failure, denial, missing-tool report, or cancellation record when a check cannot complete.

Live Odoo install and upgrade tests, Beads integration, external tracker import, Gas City packs, native agent packages, a TUI, a web UI, and Dev Container packaging belong to later releases. Odoo 19 is the initial offline validation profile. Passing it does not establish runtime or Odoo 17 compatibility.

The tested baseline is Linux with Python 3.12. Confirm other platforms through their own filesystem and process-control tests before claiming support. Dependencies are pinned in [uv.lock](../uv.lock); public package names remain undecided.

## Module design and reuse

There was no local implementation to extract. The implementation reuses standard Python distribution metadata for discovery, TOML for configuration, JSON Schema validation, and the real Go toolchain for execution. Python's [entry-point mechanism](https://packaging.python.org/en/latest/specifications/entry-points/) supports separately installed plugins. The [metadata API](https://docs.python.org/3/library/importlib.metadata.html#entry-points) separates discovery from loading an entry point.

The new [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) uses one lockfile. The implemented layout is:

```text
pyproject.toml
uv.lock
packages/
  devkit/                 foundation distribution and CLI
    src/devkit/
      contracts.py        plugin declarations, request and result types
      discovery.py        metadata discovery and activation validation
      invocation.py       CommandService and the execution pipeline
      config.py           settings resolution
      policy.py           trusted grants and authorization decisions
      processes.py        supervised subprocess execution
      evidence.py         redaction and portable bundles
      cli.py              argument parsing and rendering
  devkit_go/              separately installable Go plugin
  devkit_odoo/            separately installable offline Odoo plugin
  devkit_mcp/             separately installable local MCP adapter
tests/
  fixtures/              separately packaged contract-test plugin
scripts/check_wheels.py  independent installed-wheel acceptance
examples/                project settings, policy, and plugin template
docs/
```

The MCP distribution's optional dependencies do not enter the foundation's runtime dependency set. Package and entry-point names are provisional until public naming is checked.

`CommandService` is the deep module. Its small interface lists eligible commands and executes a command with validated input and trusted invocation context. Its implementation owns argument validation, policy decisions, handler invocation, result validation, and evidence finalization. Adapters format the result and translate transport errors. They do not call handlers directly.

Plugins depend on the public contract. The foundation discovers them through metadata and never imports Go or Odoo modules by name. Keep process execution and evidence writing behind internal seams so tests can exercise failures without exposing more plugin interface than necessary.

Use the same invocation path for checks and ordinary commands. A check declaration references a command ID and fixed arguments; profiles and environment-check declarations compose these checks. Environment checks run only when explicitly requested or required by an invocation. Discovery itself does not run checks.

The initial project contained only documentation. Slice 0 established Ruff's complexity threshold of 10; the completed implementation passes it with no functions above the threshold. Do not add pass-through modules solely to match this layout.

## Implemented first-release contracts

These defaults are implemented and tested, subject to review before a public plugin compatibility commitment.

| Contract | Implemented behavior |
| --- | --- |
| Plugin discovery | Read entry-point metadata without calling `.load()`. Display distribution name and version. Disabled or untrusted plugins do not execute registration code. |
| Activation | Require project selection plus trusted operator approval of the plugin distribution and version. Validate the entire selected registry before exposing commands. Duplicate IDs and incompatible versions fail activation deterministically. |
| Schemas | Use JSON Schema Draft 2020-12 for arguments and command-specific output. Reject invalid schemas at activation and invalid data at invocation. Disable remote schema fetching. Use one shared result envelope. |
| Versioning | Version the plugin contract and evidence schema independently from distribution releases. Declare supported versions explicitly and reject unsupported major versions. Keep the public contract provisional until both real plugins and the MCP adapter pass their tests. |
| Result status | Use `success`, `failed`, `blocked`, `error`, and `cancelled` consistently across transports and evidence. A failed check is `failed`. An unmet prerequisite or denied operation is `blocked`. A handler exception, invalid output, or deadline expiry is `error` with a stable reason code. |
| Check aggregation | Record each required check and whether it ran. The aggregate succeeds only when every required check succeeds. Skipped tests and test counts remain explicit evidence fields. A profile with no required checks does not report successful verification. |
| Handler interface | Use `handler(context, arguments) -> CommandResult`. Context supplies the resolved project root, run identity, deadline, cancellation signal, plugin settings, and surface. Handlers do not print protocol output or resolve global configuration. |
| Effects | Use `read_fs`, `write_fs`, `execute_process`, `network_read`, and `network_write`. Grants bind to a resolved project, declared effects, and surfaces. Unknown effects fail activation. Finer path/target constraints require future integrations and host enforcement. |
| Authorization | Require explicit operator grants and exact plugin version trust. A repository setting or ordinary command flag cannot relax a trusted denial. One-shot approval flows are not implemented. |
| Settings | Resolve explicit settings, project settings, user settings, then defaults. Validate unknown keys and types. Resolve project-relative paths against the selected project root, independent of the caller's working directory. |
| Process lifecycle | Use argument arrays and explicit working directories. Apply deadlines, bounded output, and environment filtering. On Linux, terminate the managed process group, allow a short grace period, then kill and reap its parent. Cleanup exceptions become errors; deliberate process detachment is outside this guarantee. |
| Python cancellation | Trusted in-process Python handlers cooperate with deadlines and cancellation. Do not advertise hard termination for arbitrary Python code. A future worker process can provide that guarantee if required. |
| CLI mapping | Exit codes are 0 for success, 1 for failed checks, 2 for blocked operations, 3 for errors, and 130 for cancellation. JSON output is one result document on stdout. Captured Python diagnostics are bounded and redacted in the envelope. |
| Evidence | Include schema version, run/parent IDs, command ID, producer/version, result, timestamps, tool versions when applicable, redacted parameters, source revision and dirty state, and bounded diagnostics. Work-item references are null; arbitrary artifacts are deferred. |
| Evidence failure | Write bundles atomically under a configured state root with restrictive permissions. If required evidence cannot be persisted, return an error and preserve the observed command outcome in the response. Never rerun a mutation automatically to repair evidence. |
| Project identity | Hash the resolved local project path with SHA-256 and record the location. Moving a project changes its identity. Git and remotes are not required; unavailable revision and dirty state are null. |

Go tests execute repository code. Their declaration must include process execution and possible filesystem and network effects. Use a dependency-free fixture to demonstrate offline operation. Running arbitrary project tests without network access requires enforcement by the host runtime. A declaration alone cannot provide that restriction.

Evidence writes and read-only Git provenance are separate, documented runtime effects. An offline validator can avoid project mutation while the runtime writes a run bundle. The runtime accepts no arbitrary artifact paths. Store bounded, redacted output and do not claim that pattern-based redaction can detect every secret.

## Implementation slices

The following slice briefs preserve the delivery sequence and acceptance gates. All six first-release slices are implemented. Dependencies identify when work could start, without requiring parallel execution.

### Slice 0: Establish the project and executable contract

Dependencies: none.

Create the new workspace, select the Python baseline, and pin development tools. Configure pytest, linting and formatting, type checks, package dependency checks, and a complexity threshold. Propose [Ruff's complexity check](https://docs.astral.sh/ruff/settings/#lint_mccabe_max-complexity) with a maximum of 10, subject to repository agreement. Define the contracts above and a minimal `doctor` command through `CommandService`.

Build a wheel and install it into a clean environment outside the workspace. The installed CLI must report its version, resolve configuration, run `doctor`, and produce schema-valid JSON and a minimal evidence bundle. It must work without a Git repository or any optional tool. Test invalid configuration and an unwritable evidence location through the public interface.

Exit gate: the first command uses the shared execution path, and CI runs the configured checks against the locked environment. A clean installation proves optional dependencies are absent.

### Slice 1: Load a separately installed plugin safely

Dependencies: slice 0.

Implement metadata discovery, explicit activation, registry validation, and command discovery. Add a tiny fixture plugin wheel for contract tests. Keep this fixture internal until the real plugins establish the contract.

Exercise installed-but-disabled, selected-but-untrusted, missing, incompatible, duplicate, malformed, and import-failing plugins. A disabled plugin containing an import side effect must leave no marker file. A command with denied effects must not invoke its handler. Repository configuration must not widen operator grants.

Exit gate: an independently installed wheel can contribute a command without a foundation source change. Invalid activation never exposes a partially built registry, and `doctor` can explain activation failures.

### Slice 2: Run a useful Go check

Dependencies: slice 1.

Implement `go.test` using the shared process runner and the installed Go toolchain. Use [Go's structured test output](https://pkg.go.dev/cmd/go#hdr-Test_packages), retain bounded diagnostic output, and record the tool version. Disable test-result caching for verification runs so the evidence describes tests executed in that run. Restrict command construction to validated arguments. Do not provide an arbitrary shell-command plugin option.

Use small passing and failing projects, a missing-tool environment, a fixture with no runnable tests, and a controlled long-running process. Exercise timeout, cancellation, output truncation, and a process with a child. Define and test the treatment of packages with no tests rather than inferring verification from exit code zero alone.

Exit gate: a clean environment containing the foundation and Go plugin produces correct evidence for success, test failure, blocked prerequisites, and interruption. It contains no Odoo packages. Managed fixture processes are reaped after timeout or cancellation.

### Slice 3: Validate Odoo addons offline

Dependencies: slice 1. Complete alongside or after slice 2, then test composition.

Implement `odoo.module.validate` for the selected Odoo 19 profile. Parse `__manifest__.py` as bounded literal data without executing it. Validate required manifest fields and declared local file paths. Report local dependency findings separately from dependencies that require a complete addon set or a running server.

Use fixtures for a valid addon, invalid manifest syntax, wrong field types, missing declared files, path traversal, symlink escape, duplicate module names, and unavailable dependencies. Include a manifest containing executable expressions and prove the validator does not execute it. Verify exact manifest rules against the pinned Odoo source or official documentation during implementation.

Exit gate: the plugin works without Odoo, RPC credentials, PostgreSQL, Docker, or the upstream SDK. Both real plugins activate together. Evidence describes static validation coverage and does not claim successful installation, upgrade, or business acceptance.

### Slice 4: Expose selected commands over local MCP

Dependencies: slices 2 and 3.

Add a separate optional MCP distribution using the official Python SDK. Pin the SDK and protocol version after checking their current documentation. Generate tools from authorized registry declarations and keep stdio protocol output separate from logs.

A read-only-looking command name is insufficient authorization. Start with explicit grants for offline validation. Expose Go execution only when its actual effects are allowed. Check authorization again when calling a tool, including after policy changes. If the selected SDK requires restricted tool names, use a deterministic, collision-checked mapping back to canonical command IDs.

Use a real stdio client to test discovery, invocation, denied and unknown tools, malformed input, invalid plugin output, and cancellation. Compare semantic results across Python, CLI, and MCP while allowing run IDs, timestamps, and transport encoding to differ.

Exit gate: every exposed tool reaches `CommandService`, unauthorized calls cannot reach a handler, and a native client completes an end-to-end invocation. Installing the foundation alone still excludes MCP dependencies.

### Slice 5: Package and demonstrate the first release

Dependencies: slice 4.

Finish user documentation, an example project manifest, the plugin template, and reusable contract-test helpers. Keep the contract helpers in the repository initially. Publish them separately only when supporting external plugin authors requires it. Verify package naming before publishing any distribution or entry-point namespace.

Run the release matrix below using built wheels in independent environments. Ensure dependency checks cover transitive imports and wheel metadata, not only imports in source files. Document the tested Python, platform, Go, and Odoo-profile versions.

Exit gate: a developer can install, activate, authorize, run, inspect evidence, and diagnose a failed check from the documentation. The release is ready for a separate publishing decision.

## First release acceptance matrix

| Environment or event | Required observation |
| --- | --- |
| Foundation only | Discovery and `doctor` work with optional packages absent. |
| Foundation with Go plugin | A real Go test passes, another fails, and missing Go blocks execution. |
| Foundation with Odoo plugin | Static validation works without an Odoo runtime or SDK. |
| Both plugins | Namespaced commands compose without foundation changes. |
| Plugin disabled or untrusted | Registration code does not execute. |
| Repository requests broader privileges | Trusted policy still denies the operation. |
| Timeout or cancellation | Managed fixture processes stop and the result records incomplete work. |
| Invalid output or evidence storage failure | The invocation returns an error and never claims successful verification. |
| No tests, missing prerequisite, or skipped required check | The result distinguishes absent coverage from successful verification. |
| Unsafe manifest path | Traversal and symlink escapes are rejected; arbitrary artifact attachments are not supported. |
| CLI, Python, and MCP | Input validation, policy decisions, and result meaning agree. |
| No Git metadata or dirty worktree | Evidence records the actual source condition without inventing a clean revision. |

Run the configured lint, format, type, test, import, and complexity checks on each affected slice. Use public invocation interfaces for behavioral tests. Use installed-wheel tests to catch undeclared dependencies that a shared workspace could hide. For subsequent bug fixes, demonstrate that the regression test fails without the fix.

## Later releases

### v0.2 practical validation milestone

Assessment before implementation: all 75 existing tests and six independent wheel
scenarios passed, as did Ruff, formatting, strict mypy, import boundaries, and
the complexity limit of 10. The P1 fixes have regression coverage in
`test_artifact_trust.py`, `test_policy_profiles.py`, and `test_runs.py`; no
regression was observed. Their documented limits remain unchanged.

The Odoo implementation currently merges every absent dependency into one
unresolved list, accepts malformed dependency identifiers, and sorts an unbounded
directory listing before applying its module limit. Manifest errors lose field
context. `doctor` checks activation but declares no Odoo environment prerequisites;
its successful foundation check does not validate addon paths or manifests.

Design: extend `devkit_odoo` using the existing literal parser, contained paths,
JSON Schema validation, `CommandResult`, check profiles, and `CommandService`.
Add `inventory.complete` and `inventory.complete_prefixes`, both empty/false by
default. Absence means unknown unless an explicit applicable completeness claim
makes it missing. Report resolved/missing/unknown/invalid relationships, inventory
coverage, and unchecked external requirements. Missing or invalid dependencies
fail; strict unknown dependencies block. Keep legacy result fields and document
the changed strict reason codes. Bound directory entries, module counts, parsing,
and output. External addon checkouts remain inside the selected workspace root.

Verification: synthetic repository fixtures through the real CLI and persisted
evidence, Python/CLI/MCP parity for dependency statuses, installed-wheel acceptance,
and a read-only public OCA snapshot evaluation. No server or dependencies are
downloaded by the validator. Reuse existing mechanisms; add no runtime packages,
plugin-contract extensions, scheduler, task tracker, or dependency solver.

Risks: completeness is a caller assertion, module presence does not prove runtime
compatibility, and malformed/unavailable inventories must never yield missing
classifications. Required improvements are dependency semantics, bounded scanning,
and actionable diagnostics. Transitive solving, cycle analysis, live external
requirement checks, and additional filesystem scopes remain follow-ups.

Delivery slices: dependency semantics and bounds; representative repositories and
usability; documented v0.2 packaging and final acceptance. Dependency semantics
and bounds are implemented; representative CLI fixtures and final acceptance
are next. See [Odoo validation](Odoo_Validation.md) for the configuration and
result contract.

### P1 follow-up slices before integration expansion

| Slice | Behavior | State |
| --- | --- | --- |
| Artifact identity | Optional operator-pinned wheel SHA-256 and installed-payload comparison before import; digest in evidence; legacy trust remains supported. | Implemented, with focused tamper tests and an independent installed-wheel scenario. |
| Reusable operator policy | Reuse complete command grants across exact canonical project paths; scoped denials override grants; repository settings cannot enroll projects. | Implemented, with scope, revocation, denial, and non-combination tests. |
| Evidence lifecycle | List/show runs without plugins; pin active-work and other references; preview or apply operator retention while protecting related runs. | Implemented, with real CLI tests for age/count/scope, references, concurrent pruners, unsafe records, and deletion failure. |

October 31 verification: 75 tests and six independent wheel environments passed,
along with lint, formatting, strict typing, import boundaries, and the configured
complexity limit of 10. Retention only recognizes locally registered references;
tracker discovery and crash-atomic family deletion remain outside this increment.

| Increment | Dependency | Deliverable and acceptance gate |
| --- | --- | --- |
| Isolated Odoo runtime checks | First release and an agreed Odoo test environment | Add install, test, and upgrade commands for a pinned Odoo 19 edition and image. Use disposable databases, explicit target authorization, and resource ownership. Prove cancellation and cleanup. Odoo 17 requires its own tested profile. Select a maintained client or a narrow transport adapter only when a concrete operation needs RPC. |
| Optional Beads adapter | First release and a pinned Beads release | Use documented machine-readable CLI operations. Test references, create, ready, claim, and close against a real isolated ledger. Prove the supported concurrent mode and conflict behavior. Do not access internal Dolt tables or initialize a user's project implicitly. |
| Odoo Project import | Beads adapter and a scoped Odoo connection | Implement one-way import and reference linking with connector-owned mappings and checkpoints. Test replay, outages, concurrent attempts, and a crash between issue creation and checkpoint persistence. Preserve external field authority. |
| Task-source independence | Beads adapter | Link an Odoo Project task to non-Odoo development and a GitHub issue reference to Odoo development. Manual GitHub reference linking is sufficient initially. A full GitHub sync connector requires separate scope. |
| Optional orchestration | Stable domain commands and the integrations the pack actually needs | Build one Gas City pack that invokes existing commands. Verify equivalent evidence for manual and orchestrated execution. Keep scheduling and agent sessions outside the foundation. |
| Additional packaging and interfaces | Demonstrated user need | Add native agent packages, Dev Container installation, or UI adapters individually. Each consumes the established invocation interface. |

The [Beads repository](https://github.com/gastownhall/beads) is the upstream starting point for its compatibility spike. Record the exact tested version and supported commands when implementing the adapter. Neither the first release nor this planning task requires adopting Beads as this project's task ledger.

## Decisions still needed

The fresh-build direction and first-release scope are confirmed and implemented. Remaining decisions concern future compatibility and integrations:

- Review the implemented status vocabulary, operator ownership, plugin trust rules, and cancellation limits before freezing the first public plugin interface.
- Select public distribution names and an owned entry-point namespace before publication.
- Select Odoo runtime environments, Beads versions, and external credentials only when scheduling those later increments.

The next integration increment needs either an agreed disposable Odoo runtime or a pinned Beads compatibility target. Neither is required to use the completed local toolkit. No public package publication or external tracker mutation has been performed.
