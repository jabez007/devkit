# Devkit implementation plan

Status: Foundation, static validation, and writable Beads integration implemented. Public publication is pending.\
Date: October 31, 2026.\
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

### CI adoption pilot design

Reuse `core.check`, project profiles, CLI exit codes, exact project grants,
wheel-artifact pins and `runs list/show/pin/prune`. These interfaces already
provide the required behavior. No runtime package, schema or version change is
needed. `scripts/check_wheels.py` already builds wheels and installs independent
environments; extend that acceptance matrix with the actual CI recipe.

Add a small synthetic combined Go/Odoo project under `examples/ci`. Its Go tests
execute normally; its custom addon is inspected offline with an explicitly
incomplete inventory. A short operator setup example creates a fresh external
policy with exact wheel versions/digests and command grants. It does not read
grants from project configuration or derive approved versions from installed
metadata. The digest proves identity with the selected build, not independent
provenance of the build source.

A Bash recipe invokes doctor and the existing verify profile, retains their JSON,
and preserves the check's exit code while retrieving evidence. Pin the profile
parent so its children stay protected. Preview retention; apply zero-retention
only inside disposable acceptance tests to prove family protection and release.
Keep the complete private state store under a fresh report directory so the
uploaded artifact can be read with `runs show --all-projects` after relocation.
Exclude operator policy, wheels and source files from that report directory.
Evidence-maintenance failure must fail a successful check and must not erase an
existing nonzero check result.

Add a GitHub Actions pilot with immutable action revisions, read-only repository
permissions, no persisted checkout credentials and a finite job timeout. Install
built wheels in a fresh environment. Upload reports on success or failure with
seven-day artifact retention. Synthetic failure scenarios remain opt-in through
workflow dispatch; default push/PR runs use the passing scenario. This workflow
executes project Go tests and is not a sandbox for arbitrary test code.

Test the recipe with actual installed wheels for success, failed Go tests,
blocked strict Odoo coverage and invalid profile configuration. Check parent/child
evidence, wheel identities, maintenance failure, relocated retrieval and pin/prune
behavior. Exercise GitHub upload/download for both successful and intentionally
failing jobs. Reuse the existing six wheel scenarios and all quality gates.
The current lint/complexity check passes; changed wheel acceptance functions
measure at most 2 against the limit of 10. No runtime cleanup is required.

GitHub artifact retention and Devkit local retention are separate lifecycles.
Cancelling or forcibly terminating a job can prevent its final upload. The pilot
does not change branch protection, publish packages or touch another project.
The three opt-in fixture mutations appear in both the Bash workflow and Python
acceptance code. Keep that small duplication: sharing it would add a scenario
runner to an example whose purpose is to demonstrate ordinary CI commands.

### CI adoption pilot completion evidence

The pilot is implemented as examples, an installed-wheel acceptance case and a
GitHub Actions workflow. It reuses the existing CLI without runtime package,
schema, dependency or package-version changes. The three existing package versions
are foundation 0.1.1, Go 0.1.0 and Odoo 0.5.0. The optional MCP package remains 0.1.0.
The guide records installation, trust, profile exits, report retrieval, local
retention and provider artifact expiration.

Final local verification on October 31, 2026:

| Command | Observed result |
| --- | --- |
| `.venv/bin/ruff check .` | Passed, including complexity limit 10. |
| `.venv/bin/ruff format --check .` | Passed; 124 Python files formatted. |
| `.venv/bin/mypy` | Passed; 26 runtime source files under strict checking. |
| `.venv/bin/lint-imports` | Passed; foundation optional-import boundary kept. |
| `.venv/bin/pytest -q` | 234 passed in 63.01 seconds. |
| `.venv/bin/python scripts/check_wheels.py` | All seven independent environments passed, including the original 33 Odoo CLI fixtures and seven new CI recipe scenarios. |
| `bash -n examples/ci/check.sh` | Passed. The actual recipe was also exercised by the wheel acceptance cases. |
| `gofmt -l examples/ci/project/total.go examples/ci/project/total_test.go` | Passed with no files reported. |

The first wheel run exposed that naming the policy script `operator.py` shadows
Python's standard module. Renaming it to `prepare_policy.py` fixed startup; the
full wheel matrix then passed. A later two-line fault-injection refinement changes
Go's calculation instead of its assertion, producing a useful "got 11; want 10"
diagnostic. All seven pilot cases passed again against installed wheels after
that refinement. Exact workflow build, lock export, installation, operator setup
and check commands also passed in a fresh local environment before workflow push.

The maximum measured complexity in changed Python functions is 4 against the
limit of 10. No suppressions were added. The existing bare-manifest lint exception
was extended to the new literal example manifest. No runtime cleanup was needed.
Host execution was used for Go/process/MCP and wheel checks because restricted
sandbox stdio cannot complete them. All required gates ran; documentation links
were checked locally.

[Hosted acceptance](CI_Pilot.md#verified-pilot-runs) establishes a successful
combined profile and three deliberately failing jobs with exits 1, 2 and 3.
Every job uploaded reports. Downloaded artifacts preserved their results,
revision/dirty identity and pins, and were readable with an independent
foundation-only installation. Their pinned families survived a zero-retention
preview. Artifact metadata confirmed seven-day provider retention.

Remaining limits: this is a synthetic project, not a client adoption. The wheel
hash approves identity with the selected build, not independent build provenance.
Go tests execute under the runner's permissions. Provider expiration is independent
of local pins, and forceful cancellation can prevent report upload. No package was
published, no branch-protection rule changed, and no other repository was modified.

Next, choose a real development repository and adapt its check profile and
operator policy. Use its feedback before expanding static checks or integrations.
Runtime Odoo, external task tracking and orchestration remain separately scoped.

### v0.5 observed dependency-cycle diagnostics design

Reuse `module_dependencies`, the inspected module findings, `Inventory`, the
existing result envelope and persisted evidence. Add graph analysis inside the
Odoo dependency module. Its interface accepts findings and inventory names; it
performs no filesystem reads. The selected-module seam stays unchanged: selecting
one module does not read the manifests or data files of its dependencies.

Python's standard-library `graphlib.TopologicalSorter.prepare` already detects
cycles and returns a closed witness through `CycleError`. Use it instead of a new
graph dependency or handwritten traversal. Report one witness, not every cycle
or an installation order. Reverse the predecessor-oriented witness so each
reported step means "this module depends on the next module". Sort and deduplicate
known edges before analysis. Inventory and findings-size bounds already bound
this graph; preserve cancellation checkpoints before and after graph analysis.

Specialization data schema 1.4 adds `dependency_graph` with its inspection status,
node/edge counts, one closed cycle when found, excluded declaration counts and
uninspected inventory modules. Per-module `dependencies_inspected` distinguishes
unreadable manifests from valid empty declarations. Only resolved edges between
inspected manifests enter the graph. Valid edges can prove a cycle even when
other declarations are invalid or unknown. Never infer missing edges or cycles
from completeness claims. "No cycle observed" applies only to this graph and is
not a runtime compatibility guarantee.

A confirmed cycle fails with `DEPENDENCY_CYCLE`, before blocked coverage; existing
invalid-manifest/dependency, malformed-data and missing-dependency precedence
stays intact. Those failures still retain any cycle evidence. Strict unknown
module dependencies continue to block as before. Human output names the cycle
and directs the developer to the manifests. The generic plugin contract does
not change. This is static graph inspection, not a transitive dependency solver.

The current complexity gate passes; `_inspect` is 8 and `_outcome` is 7 against
limit 10. No unrelated cleanup is required. Test self-cycles, asymmetric cycles,
shared-dependency DAGs, disconnected cycles, duplicate edges, unknown/invalid
edges, implicit base dependencies, selection, invalid manifests, cancellation,
output limits and long graphs through the command interface. Then add real
CLI/evidence and MCP parity fixtures, run the independent-wheel matrix, recheck
the pinned public OCA snapshots read-only, and update package/docs versions.

Reference: [Python graphlib](https://docs.python.org/3.12/library/graphlib.html)
and the pinned Odoo [module graph](https://github.com/odoo/odoo/blob/005e0a0eb7ef80cd15b0c82b570b2b0843181ba2/odoo/modules/module_graph.py).
Odoo skips modules in dependency loops. The first regression run failed all 15
new cases. It also exposed that cancellation during the new graph phase must
share the existing validation error handler. Move that handler to encompass both
inspection phases, avoiding a second handler or a new wrapper.

### v0.5 completion evidence

Completed in two tested slices: cycle analysis with coverage and cancellation;
representative acceptance, public evaluation and versioned documentation.
devkit-odoo is 0.5.0 with specialization data schema 1.4. The foundation remains
0.1.1 and Go/MCP remain 0.1.0. There are no dependency or generic contract changes.
Update exact plugin trust and approved wheel digests when upgrading Odoo.

The feature slice passed 225 tests and all six independent wheel scenarios. The
new tests were observed failing before implementation. Cancellation during graph
analysis initially became an error; sharing the existing validation handler
fixed that regression. An older XML test used a self-dependency to simulate a
complete inventory. It now uses a separate synthetic base addon so its original
XML-ID coverage assertion remains intact without an invalid dependency loop.

Final commands executed October 31, 2026:

| Command | Observed result |
| --- | --- |
| `.venv/bin/ruff check .` | Passed, including complexity limit 10. |
| `.venv/bin/ruff format --check .` | Passed; 120 Python files formatted. |
| `.venv/bin/mypy` | Passed; 26 source files under strict checking. |
| `.venv/bin/lint-imports` | Passed; foundation optional-import boundary kept. |
| `.venv/bin/pytest -q` | 234 passed in 62.01 seconds. |
| `.venv/bin/python scripts/check_wheels.py` | All six independent installation scenarios passed, including 33 Odoo CLI cases. |
| `.venv/bin/python scripts/check_odoo_fixtures.py .venv/bin/devkit` | 33 cases passed with persisted evidence, retrieval and text diagnostics. |

A separate Ruff measurement found a maximum of 8 in changed runtime code and
the fixture assertion helper. `_inspect` decreased from 8 to 7; `_outcome`
increased from 7 to 8 to classify confirmed cycles. No complexity suppressions
were added. Graph behavior stays in the existing dependency module. No additional
cleanup or new abstraction was needed. Process/MCP and wheel tests ran on the
host because restricted sandbox stdio cannot complete them. No required gate was
skipped. Local links in all five edited Markdown documents were checked.

The fixture corpus has 24 layouts and 33 CLI scenarios. Seven new cycle scenarios
cover self-dependency, three-module loops with unknown dependencies, selected
modules, shared-dependency DAGs and loops across addon paths. MCP parity adds a
confirmed cycle failure and a selected-module success with explicit graph gaps.
Tests preserve P1 artifact trust, policy profiles, evidence retention, Go
independence and foundation-only operation. A 500-module cycle retains its full
closed witness in evidence while bounding the human summary.

[Public evaluation](Odoo_Validation.md#v05-public-repository-evaluation) examined
133 manifests and 19 known edges in two pinned OCA repositories. No cycles were
observed. The 156 unknown dependency declarations were excluded explicitly;
ordinary validation succeeded and strict validation blocked on incomplete
inventory. Evidence and retrieval matched, and both checkouts remained clean.
These snapshots establish correct coverage reporting, while synthetic fixtures
establish cycle detection.

One witness does not enumerate every cycle. Uninspected manifests, unresolved
edges and runtime effects remain outside graph coverage. A selected-module check
retains its existing read scope. No installation order, full solver or runtime
compatibility guarantee was introduced.

### v0.4 bounded CSV identifier inspection design

Extend the existing Odoo command to inspect manifest-declared CSV data/demo files.
Reuse contained paths, manifest ordering, cancellation, status/evidence handling
and the literal reference resolver. The public v0.3 corpus has 33 declared CSV
files and 107 nonempty rows, all using flat access-control headers.

The resolver is currently named for XML despite its format-independent events.
Rename that internal module and extract the declared-file inspection seam in a
behavior-preserving commit before adding the second format. Extract the existing
bounded file read into a shared FileBudget to avoid duplicating byte/file limits
and cancellation across the two inspectors. Each format keeps its own budget.
Keep concrete XML
and CSV inspectors; no general-purpose parser registry or generic plugin change.
The configured complexity check passes, with a maximum of 8 in changed runtime
functions. No unrelated cleanup is required.

Use the standard-library csv reader with explicit comma/double-quote settings,
UTF-8 decoding and bounded bytes, files, rows, columns, fields and retained events.
Do not change the process-global CSV field-size limit. The pinned Odoo loader uses
a permissive CSV reader, so rejection by strict CSV parsing establishes unsupported
inspection, not necessarily a broken import. Empty files and invalid UTF-8 are
confirmed violations of that loader's requirements. Ambiguous headers, irregular
rows, nested paths, BOMs and inspection limits block coverage without inventing a
runtime defect. Ignore translation columns as the pinned loader does.

Support literal id declarations and single literal values in direct field:id or
field/id columns. Do not infer relational cardinality or split ambiguous comma
lists. Normalize names through the existing resolver, preserve data/demo and row
order, and allow repeated IDs. Empty IDs create no inferred identity. Cross-module,
forward and unsupported references remain unknown, never definitely missing.
XML-ID completeness is separate from module inventory claims. Runtime model and
field validity, conversions, permissions and hooks remain unchecked.

Add csv file findings/counts beside existing xml data in specialization schema
1.3. Preserve XML fields and reason vocabulary for existing consumers. Reuse the
legacy xml.skipped_files location for files neither inspector examines, avoiding
duplicate evidence; document this compatibility choice. Generic contracts and
strict module-dependency semantics stay unchanged.

Deliver bounded CSV inspection and shared resolution, then representative CLI/MCP
and installed-wheel acceptance, public evaluation and documentation. Test quoted
and multiline fields, translations, empty/repeated/foreign IDs, mixed file order,
data/demo separation, malformed and unsupported input, bounds, cancellation and
no execution of cell contents. Retain all earlier quality gates and P1 regressions.

Sources: pinned Odoo [CSV loader](https://github.com/odoo/odoo/blob/005e0a0eb7ef80cd15b0c82b570b2b0843181ba2/odoo/tools/convert.py)
and [importer](https://github.com/odoo/odoo/blob/005e0a0eb7ef80cd15b0c82b570b2b0843181ba2/odoo/orm/models.py),
and the [Python CSV interface](https://docs.python.org/3.12/library/csv.html).

### v0.4 completion evidence

Completed in three slices: shared bounded reads and reference inspection;
CSV inspection and mixed-format resolution; representative acceptance, public
evaluation and versioned documentation. devkit-odoo is 0.4.0 with data schema
1.3. The foundation remains 0.1.1 and Go/MCP remain 0.1.0. No dependencies or
generic plugin contracts changed. Exact operator trust and pinned wheel digests
must be updated when installing the new Odoo wheel.

The baseline passed 169 tests. The refactor passed 73 focused tests, and the
feature slice passed 201 full-suite tests and the six-environment wheel matrix.
A regression for blank or translation-only rows was observed failing before the
fix: the loader removes translation columns and ignores empty rows before import,
so width checks must not falsely block those rows.

Final commands executed October 31, 2026:

| Command | Observed result |
| --- | --- |
| `.venv/bin/ruff check .` | Passed, including complexity limit 10. |
| `.venv/bin/ruff format --check .` | Passed; 99 Python files formatted. |
| `.venv/bin/mypy` | Passed; 26 source files under strict checking. |
| `.venv/bin/lint-imports` | Passed; foundation optional-import boundary kept. |
| `.venv/bin/pytest -q` | 210 passed in 52.75 seconds. |
| `.venv/bin/python scripts/check_wheels.py` | All six independent installation scenarios passed. The Odoo-only scenario includes all 26 CLI fixture cases. |
| `.venv/bin/python scripts/check_odoo_fixtures.py .venv/bin/devkit` | 26 cases passed, including persisted evidence, retrieval and text diagnostics. |

A separate Ruff measurement found maximum complexity 8 in the changed Odoo code
and fixture assertion helper. No suppressions were added. Process/MCP and wheel
checks ran on the host because restricted sandbox stdio cannot complete them.
No required gate was skipped. The shared FileBudget and reference resolver remove
format duplication; no additional cleanup or new abstraction is needed now.

The twenty synthetic layouts cover mixed XML/CSV ordering, access controls,
forward/demo references, updates, translations, multiline fields, malformed input
and unsupported layouts. Python tests cover bounded inspection, cancellation,
unsafe paths and inert cell contents. CLI/Python/MCP parity covers CSV success,
defects, blocked coverage and authorization. P1 trust, policy and retention
regressions remain in the full suite; foundation-only and Go independence remain
in the wheel matrix.

[Read-only public evaluation](Odoo_Validation.md#v04-public-repository-evaluation)
inspected all 33 previously skipped CSV files and 107 nonempty rows across the
same two pinned OCA snapshots. CSV findings report 2 resolved and 212 unknown
references. Existing XML resolution counts did not change. Ordinary validation
succeeded and strict module-dependency checks blocked on incomplete inventory;
both checkouts remained clean and results matched persisted evidence. Synthetic
fixtures establish the added cross-format resolution behavior.

Runtime model metadata, relational cardinality, nested imports, conversions,
permissions and hooks remain unverified. Unsupported CSV shapes block coverage;
unknown IDs are advisory and never asserted missing. There is no runtime import
or record-existence guarantee.

For the next milestone, prioritize bounded dependency-cycle diagnostics among
observed modules, reusing the existing inventory and result envelope. Prove
cycles only from known edges and preserve incomplete-inventory semantics. Then
use public results to select further static checks. Runtime Odoo operations and
orchestration remain separately scoped future work.

### v0.3 offline XML validation design

Reuse the Odoo command, literal manifests, contained-path checks, cancellation
checkpoints, result envelope and evidence store. The existing `_check_files`
seam already visits manifest `data` and `demo` files. Extend it to inspect declared
XML automatically and preserve file order and phase. Keep XML parsing and literal
reference analysis inside the Odoo specialization, behind one inspection module
interface. No generic plugin-contract changes or runtime dependencies are needed.

Use the standard-library Expat callbacks for source locations and bounded event
inspection. Reject DTDs before declarations can expand entities. Never resolve
external entities, evaluate expressions, process XInclude or import addon code.
Bound per-file and invocation bytes, file count, element count, nesting depth and
retained reference events. Reuse the existing final findings-size limit.
Malformed XML is a defect; unsupported constructs, unreadable XML and exhausted
inspection limits are missing coverage and block validation. Preserve any
confirmed defects alongside blocked coverage in structured results.

Literal reference analysis will cover a documented subset of Odoo loader
operations, with source locations and data/demo ordering. Earlier same-module
literal definitions can resolve a reference within the static inspection.
Forward, external, dynamic and unseen references remain unknown. XML inventory
cannot establish XML-ID absence: CSV, model metadata, hooks and installed data can
supply IDs. Repeated definitions may be updates, so do not report duplicates as
inherently invalid. No database simulation or XML-ID completeness setting.

The additive specialization data schema becomes 1.2. Existing dependency
classification and strict-dependency behavior remain unchanged. New XML results
must explain examined files, unsupported forms and runtime limits. Syntax errors
may make previously passing projects fail; document this intended behavior.

Delivery uses three tested slices: bounded XML syntax diagnostics; literal
reference diagnostics; representative CLI/wheel fixtures, public evaluation and
versioned documentation. Test through CommandService, CLI evidence and MCP,
including malformed and hostile XML, encodings, bounds, file order, data/demo
separation, updates and unresolved references. Run all existing quality gates.
The baseline Ruff complexity check passes; `read_manifest` measures 8 against
limit 10. No unrelated cleanup is required by this change.

References checked before implementation: the pinned Odoo 19
[XML loader](https://github.com/odoo/odoo/blob/005e0a0eb7ef80cd15b0c82b570b2b0843181ba2/odoo/tools/convert.py),
[Expat interface](https://docs.python.org/3.12/library/pyexpat.html), and
[Python XML limits](https://docs.python.org/3.12/library/xml.html).
Parser bounds and feature restrictions do not replace maintaining the Python
runtime and its linked Expat library.

### v0.3 completion evidence

All three slices are implemented. devkit-odoo is 0.3.0; the foundation remains
0.1.1 and Go/MCP remain 0.1.0. The specialization data schema is 1.2, with no new
runtime dependencies or generic plugin-contract changes. Update exact operator
trust and any pinned wheel when installing the new specialization.

The existing suite passed 119 tests before implementation. The syntax and
reference slices passed 141 and 157 tests respectively, each with the independent
wheel matrix. New regressions were observed failing before implementation,
including malformed XML passing validation and valid UTF-32 being mislabeled as
malformed. UTF-32 now blocks as unsupported. Cancellation follows the existing
foundation contract and persists a cancelled result without claiming partial
inspection completed.

Final commands executed October 31, 2026:

| Command | Observed result |
| --- | --- |
| `.venv/bin/ruff check .` | Passed, including complexity limit 10. |
| `.venv/bin/ruff format --check .` | Passed; 84 Python files formatted. |
| `.venv/bin/mypy` | Passed; 24 source files under strict checking. |
| `.venv/bin/lint-imports` | Passed; foundation optional-import boundary kept. |
| `.venv/bin/pytest -q` | 169 passed in 42.97 seconds. |
| `.venv/bin/python scripts/check_wheels.py` | Six independent installations passed, including all twenty Odoo CLI fixture cases. |
| `.venv/bin/python scripts/check_odoo_fixtures.py .venv/bin/devkit` | Twenty cases passed, with persisted evidence, retrieval and human output. |

The highest measured complexity in the changed specialization is 8, in
`read_manifest` and `_resolve`. No complexity suppression was added. Process/MCP
and wheel checks ran on the host because restricted sandbox stdio cannot complete
those checks. No required gate was skipped.

The corpus now contains fourteen synthetic layouts. MCP parity includes XML
success, syntax failure and blocked DTD inspection, alongside the existing module
dependency and authorization cases. All prior artifact-trust, operator-profile,
evidence-retention, Go independence and foundation-only regressions remain in the
suite and wheel matrix.

[Two public OCA snapshots](Odoo_Validation.md#v03-public-repository-evaluation)
provided a read-only evaluation of 133 modules and 299 XML files. Ordinary
validation succeeded; strict module-dependency checks blocked on incomplete
inventory. Both checkouts remained clean, and CLI results matched saved evidence
and `runs show`. Reference diagnostics reported 104 resolved references to earlier local
definitions and 439 unknown references, with unsupported operations and non-XML files explicitly
recorded. These counts establish static inspection coverage, not runtime Odoo
compatibility.

The remaining limits are intentional: no database, XPath/view validation,
dynamic evaluation, CSV-content inspection, cross-module XML-ID solver or runtime
record-existence guarantee. Caller-declared module completeness cannot establish
XML-ID completeness. Existing infrastructure was sufficient; no unrelated cleanup
or architectural redesign was needed.

### v0.2 practical validation milestone

Assessment before implementation: all 75 existing tests and six independent wheel
scenarios passed, as did Ruff, formatting, strict mypy, import boundaries, and
the complexity limit of 10. The P1 fixes have regression coverage in
`test_artifact_trust.py`, `test_policy_profiles.py`, and `test_runs.py`; no
regression was observed. Their documented limits remain unchanged.

At assessment, the Odoo implementation merged every absent dependency into one
unresolved list, accepted malformed dependency identifiers, and sorted an unbounded
directory listing before applying its module limit. Manifest errors lost field
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
and bounds, representative CLI fixtures, and focused usability improvements are
implemented. Versioned packaging uses devkit-odoo 0.2.0 and foundation 0.1.1;
Go/MCP remain at 0.1.0. The specialization data schema is additive 1.1, and the
generic contracts remain unchanged. Exact Odoo trust versions and optional wheel
pins must be updated. See [Odoo validation](Odoo_Validation.md) for configuration,
compatibility and the public repository evaluation.

The fixture corpus covers nine synthetic repository layouts and fifteen CLI
cases. Both development and independent Odoo-only installations exercise the
same cases, human output, persisted evidence, and evidence retrieval. MCP tests
compare complete result objects against CLI and Python for resolved, unknown,
missing and invalid dependencies, retaining authorization and revocation checks.
Doctor now states its scope and exposes safe activation diagnostics; CLI errors
identify configuration files and classify malformed JSON as invalid input.
These reuse existing summaries and redaction, with no domain branches in core.
The four CLI regressions were observed failing before their fixes. No new runtime
dependencies were added. Ruff's complexity limit remains 10; the manifest-only
B018 exemption permits Odoo's required bare dictionary syntax, not complex code.

### v0.2 completion evidence

Executed October 31, 2026 from the locked workspace environment:

| Command | Observed result |
| --- | --- |
| `.venv/bin/ruff check .` | Passed, including configured maximum complexity 10. |
| `.venv/bin/ruff format --check .` | Passed; 70 Python files formatted. |
| `.venv/bin/mypy` | Passed; strict checking of 22 source files. |
| `.venv/bin/lint-imports` | Passed; foundation optional-import boundary kept. |
| `.venv/bin/pytest -q` | 119 passed in 34.65 seconds. |
| `.venv/bin/python scripts/check_wheels.py` | Six independent installed environments passed, including the 15 Odoo CLI cases. |
| `.venv/bin/python scripts/check_odoo_fixtures.py .venv/bin/devkit` | Fifteen CLI cases passed, including text, persisted evidence and retrieval. |

Process/MCP and installed-wheel checks ran in the host execution environment;
restricted sandbox stdio cannot complete those tests. No required gate was
skipped. A separate Ruff complexity measurement found a maximum of 8 in changed
runtime functions (`read_manifest`); no complexity exemptions were introduced.
No additional cleanup requiring an unrelated refactor was identified.

The [public OCA evaluation](Odoo_Validation.md#representative-validation) examined
30 modules at a pinned clean revision: 2 resolved relationships, 30 unknown,
none missing or invalid, and 8 unverified external requirements. Ordinary
validation succeeded; strict validation blocked with `INCOMPLETE_INVENTORY`.
Both runs' persisted evidence and retrieval were checked.

| Milestone acceptance | Evidence |
| --- | --- |
| Custom addons without a server or complete Odoo checkout | Standalone fixture and independent Odoo-only installation. |
| Missing, unknown and invalid remain distinct | Explicit full/prefix claims, incomplete and malformed fixture regressions. |
| Strict validation cannot infer completeness | Incomplete strict CLI/MCP cases block; unavailable scans never classify absence as missing. |
| Go remains independent | Real passing/failing Go wheel tests with Odoo absent. |
| Foundation remains independent | Foundation-only wheel tests, including doctor and evidence lifecycle. |
| CLI/Python/MCP semantics remain consistent | Result equality for all dependency statuses, denial and revocation regressions. |
| Prior P1 fixes remain covered | Artifact trust, operator profiles and evidence retention suites plus installed tamper scenario. |
| Behavior is documented and demonstrated | README, specialization guide, architecture decision D9, synthetic fixtures and public evaluation. |

Declared completeness is still a claim; the validator cannot certify that a
caller supplied every source. Resolved means direct manifest presence. Runtime,
transitive dependency/cycle analysis and external requirement checks remain
outside coverage. These limits are exposed in results and documentation.

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
| Optional Beads adapter | Inspection and writable lifecycle implemented | Beads 1.3.2 embedded workspace inspection, local evidence references, create, claim, update, comment and close. Server, administrative and simultaneous-writer modes remain separately scoped. |
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

Prioritize the next practical milestone as follows:

1. Adopt the verified CI pilot in a selected real development repository. Review
   that project's check profile, operator grants and evidence-upload contents.
2. Use that adoption feedback to select the next static check or output improvement.
   v0.4 CSV inspection and v0.5 observed-cycle diagnostics are implemented; neither
   establishes runtime record existence or global dependency completeness.
3. Schedule live runtime validation only with an explicitly agreed disposable
   Odoo environment. Beads inspection and ordinary task mutations are implemented;
   orchestration and administrative commands remain separately scoped proposals.

No public package publication or external tracker mutation has been performed.


## v0.6 design note — foundation integration

The optional `devkit-beads` adapter will use the existing specialization entry
point, command registry, policy checks, invocation service, process supervisor,
and `RunStore.reference`/`show` interfaces. Beads remains the authority for work
items and readiness. No task database, scheduler, or Beads work-item writes are introduced.

The tested upstream interface is Beads 1.3.2, commit
`9b65b9e198acbcc98e7fd3a87a5d55baa065a572`. An initial content-only probe of `context`,
`show`, `ready`, and `dep list` left workspace contents unchanged when showing
the already last-touched item. Subsequent acceptance exposed `show` marker
writes and Dolt timestamp updates; the findings and final contract are recorded
below. Explicit read-only mode disables maintenance and
server auto-start; `BD_DISABLE_METRICS=1` disables telemetry initialization.
Initial support is an embedded Dolt workspace at the project root. Other
versions, redirects, worktrees, and server backends require separate validation.

Two additive foundation seams are necessary: `Context.state_root` supplies the
already-resolved evidence location, and `run_process(..., environment=...)`
accepts an explicit child environment without inheriting unrelated variables.
Existing callers retain their defaults. These additions avoid configuration
re-resolution and a duplicate subprocess supervisor. Foundation 0.1.2 keeps
plugin API 1.0 and envelope 1.0; the new adapter requires that patch release.
The adapter owns Beads JSON parsing, compatibility checks, and qualified identity
(`beads:<project UUID>:<issue ID>`). No generic issue interface is needed.

Association validates the existing run and live work item, then atomically adds
its qualified reference to the existing local pin set. The immutable original
envelope remains unchanged. Repetition is idempotent; an invocation-evidence
failure after pinning is reported by the existing `observed_result` mechanism
and can be retried. Pins protect evidence, not task completion or approval.
Copies of evidence must include `references.json` to carry associations;
retrieval uses existing `runs show` without requiring the adapter.

Slices: (1) additive foundation seams; (2) read-only Beads commands;
(3) association and retention; (4) independent plugin and real installed-wheel
acceptance; (5) documentation and full gates. Tests cover policy denial before
execution, malformed/bounded output, missing tools, cancellation, incompatible
workspaces, association retries and partial failures, and CLI/Python/MCP parity.
Real disposable Go and Odoo workspaces exercise Beads 1.3.2. Existing P1 suites
and foundation/Go/Odoo-only wheels remain regression gates.

Baseline Ruff complexity checks passed at the configured maximum of 10.
No existing over-threshold functions or required broad refactors were found.
The process helper is already shared with Go; this concrete second consumer
justifies documenting its narrow interface. Remote Beads modes and automatic
association removal on task closure are follow-ups, not part of this milestone.

Slice 1: the two additive seams passed 50 focused tests (foundation, processes,
Go, evidence lifecycle, artifact trust, and policy profiles), plus lint,
formatting, strict typing and import boundaries. A stale hardcoded foundation
producer version was observed failing a regression test and now uses the package
version. The new seam tests also failed before implementation.

Slice 2 adds the independently installed Beads read adapter. Its explicit process
environment disables metrics and selects this project's `.beads`. All commands
use `--readonly --sandbox --json`; no command initializes, migrates, or updates
work items. Read effects include `network_read` conservatively because Beads
configuration can select a remote backend before the adapter rejects that mode.
`beads.workspace` is an existing environment-check prerequisite, so doctor and
all item commands explain unsupported setup consistently. Commands repeat the
workspace check at their own invocation to avoid relying on cached identity.

Slice 3 uses `RunStore` references directly. Association accepts completed runs
of any outcome and reports that outcome without changing it. Missing, incomplete,
and foreign-project runs cannot be linked. Tests cover idempotence, retained
original evidence, pruning protection, missing work items, reference-write failure,
and evidence-write failure after a successful pin. Beads work items receive no writes.

Installed-wheel testing exposed a Beads prerequisite that the controlled CLI
fixture did not establish: `bd init` succeeds outside Git, but `bd context` cannot
resolve that workspace. Real acceptance now initializes disposable Git repositories
before their Beads ledgers, and the integration guide states the requirement.
The adapter already reports this unavailable context as blocked.

Real acceptance also caught a Beads 1.3.2 `show` side effect: it writes
`.beads/last-touched` even with `--readonly`. The initial same-item/content-only
probe did not detect this. Item retrieval now uses supported `list --id` with
explicit inclusion flags and a two-row bound, validating the exact returned ID.
Acceptance compares contents and mtimes, including the isolated user home. No
upstream patch, copied database, or compensating workspace write is needed.

The timestamp check exposed an additional upstream limitation: embedded Dolt
reads rewrite internal database files with identical bytes. The adapter now
conservatively declares `write_fs` for read commands as well as association.
Acceptance requires unchanged workspace file contents and all non-database
mtimes, plus an unchanged isolated home during Beads queries; it reports internal timestamp updates
explicitly. Logical work-item read-only behavior is established, but strict
filesystem read-only operation remains unverified/unsupported. This is a stated
milestone limitation, not an assertion that `--readonly` prevents every write.
No broad storage workaround or upstream patch is introduced.

Real installed acceptance now passes in both Go and Odoo repositories, including
CLI/Python/MCP association parity, repeated references, protected aggregate runs,
and copied evidence read by foundation-only environments. The original run bytes,
Beads work-item contents, last-touched marker, and Beads-query user-home state
remain unchanged. Go's separately authorized cache writes are measured outside
the Beads preservation interval. Ruff measurement reports maximum complexity 7
for the changed process helper and Beads runtime, and 4 for the independent
README example, below the configured threshold 10. No complexity suppression or
new third-party Python dependency was introduced.


### Historical v0.6 verification and initial read-only interpretation

Executed October 31, 2026 using the locked workspace environment:

| Command | Observed result |
| --- | --- |
| `.venv/bin/ruff check .` | Passed, including complexity maximum 10. |
| `.venv/bin/ruff format --check .` | Passed; 133 Python files formatted. |
| `.venv/bin/mypy` | Passed; 29 runtime source files checked strictly. |
| `.venv/bin/lint-imports` | Passed; foundation cannot import the Beads or other optional packages. |
| `.venv/bin/pytest -q` | 258 passed in 69.99 seconds. Includes the existing P1 regressions and Beads failures, cancellation, parity, revocation and retries. |
| `DEVKIT_BEADS_BINARY=/tmp/devkit-beads-1.3.2/bd .venv/bin/python scripts/check_wheels.py` | Passed in 12 independent installed environments. Includes 33 Odoo CLI fixtures, seven CI recipe scenarios, a renamed third-party package, real Beads Go/Odoo workflows, and two foundation-only portable evidence readers. |

The first wheel attempt caught the missing Git prerequisite. The next real
acceptance attempt caught `show` changing the last-touched marker. After the
exact-ID list correction, stronger timestamp checks identified identical-byte
embedded Dolt rewrites. The final checks retain content and non-database marker
preservation assertions and explicitly report this upstream limitation. No tests
or complexity warnings were suppressed. Current Beads queries are logically
read-only, but a strict no-filesystem-writes interpretation of the requested
read-only criterion remains unmet. It should not be represented as established.

The third-party exercise copies the existing template outside this checkout,
renames its packaging and namespace, supplies the bounded README check, and
builds a normal wheel. Its valid/failed results match on CLI, Python and MCP;
non-regular input blocks without hanging. Discovery, trust, policy denial,
evidence, deactivation and uninstall are exercised with an unrelated plugin
remaining usable. Documentation now makes the Hatch package-path rename and
uninstall/deactivation order explicit. No new plugin framework or testing SDK
was necessary.

Remaining scope: Beads 1.3.2 embedded Git repositories only; no concurrent-writer,
server, worktree, redirect or other-version guarantee. Associations are local
references with explicit operator removal, not continuously synchronized links.
No Odoo validator, task lifecycle, orchestration, or public registry publication
was added. The independent package versions are foundation 0.1.2, Beads 0.1.0,
Go/MCP 0.1.0 and Odoo 0.5.0; plugin/evidence schemas remain 1.0.

The original recommendation to prioritize strict storage read-only access is
superseded by the writable integration below. Read-only task access remains an
optional restricted configuration. Embedded bookkeeping is not a reason to block
ordinary development workflows. Current priorities are a selected repository
pilot and compatibility expansion based on observed needs. Administrative
operations and orchestration remain separately scoped.


## Writable Beads integration design

The v0.6 read-only scope was an initial delivery choice, not an architectural
constraint. Normal development now needs explicit create, claim, update, comment,
and close commands. Beads remains authoritative for identity, transitions,
conflicts, dependencies and closure rules. Inspection remains an optional
restricted policy configuration, with no task mutations granted.

Reuse `Beads.workspace`, qualified references, the shared subprocess supervisor,
`CommandSpec` input schemas, exact-command policy grants and invocation evidence.
Evidence association continues to use `RunStore.reference` unchanged. No core
lifecycle logic, permission framework, issue cache, retry database or orchestration
is needed. The adapter's CLI seam will distinguish queries from explicit writes.
A small extraction of supervised invocation prevents duplicated process handling;
it is verified and committed separately before adding mutation behavior.

Expose `beads.item.create`, `beads.item.claim`, `beads.item.update`,
`beads.item.comment`, and `beads.item.close`. Require an explicit audit actor for
writes. Limit updates to ordinary fields and non-closed standard statuses, with
optional native Beads compare-and-set guards. Closing has its own command grant.
No force, delete, purge, migration, arbitrary argv, automatic next-task selection,
or administrative command is exposed. Writes use Beads 1.3.2's supported CLI,
retain `--sandbox` to suppress automatic Dolt pushes, and declare all existing
effects conservatively because native writes can run configured maintenance/hooks.
Actor is an audit label, not a new authorization identity. Operator policy grants
remain the authority for trusted users and agents.

Use one policy example with separately listed command grants. Omitting the five
mutation grants retains the restricted configuration. Effects alone do not grant
commands. No additional profile or repository-controlled permission switch is
needed. Bump only devkit-beads to 0.2.0 so exact-version trust must be renewed.

Evidence association remains idempotent and never completes a task. Other writes
are issued once, with no automatic replay. Beads owns atomic claiming and guarded
updates. Creation may supply an explicit qualified reference for reconciliation.
Comments and generated-ID creation can duplicate on manual retry after an unknown
outcome; report uncertainty rather than invent exactly-once semantics. Validate
successful response identity and shape before claiming success. Cancellation,
timeout, nonzero exit and malformed replies may follow a committed write.

Tests will cover actual CLI writes in disposable Go and Odoo Git repositories,
native claim/guard conflicts, closure blockers, audit actors, literal flag-like
text, denied writes before process execution, all invocation interfaces, restricted
configuration, interrupted/malformed writes, and existing association retries.
Run the full lint, format, strict typing, import, pytest and installed-wheel gates.
Baseline complexity passes at threshold 10. The current query function measures
7; extraction keeps process policy local. No unrelated cleanup is required.


Writable integration verification so far: 52 focused tests pass, including all
five mutations on CLI, Python and MCP, denied/invalid calls before execution,
revocation, explicit actors and effects, uncertain results, cancellation, native
guard failures and evidence persistence failures. The original association tests
remain unchanged in behavior. Actual installed Beads acceptance passed in both
Go and Odoo repositories: create, claim and same-actor retry, competing claimant
refusal, guarded update conflict, comment through MCP, verification, repeated
association, blocked closure, successful closure and retention. Beads recorded
exactly one explicit comment; evidence association added none. The shared
invocation extraction separately passed 22 regressions before lifecycle code.


### Writable integration final verification

Executed October 31, 2026 after implementing the lifecycle commands:

| Command | Observed result |
| --- | --- |
| `.venv/bin/ruff check .` | Passed, including complexity limit 10. Changed Beads functions measure at most 6. |
| `.venv/bin/ruff format --check .` | Passed; 136 Python files formatted. |
| `.venv/bin/mypy` | Passed; 30 runtime source files checked strictly. |
| `.venv/bin/lint-imports` | Passed; foundation remains independent of Beads. |
| `.venv/bin/pytest -q` | 289 passed in 87.14 seconds. All five mutations have successful invocation and denial coverage across CLI, Python and MCP. |
| `DEVKIT_BEADS_BINARY=/tmp/devkit-beads-1.3.2/bd .venv/bin/python scripts/check_wheels.py` | Passed across 12 installed environments, including writable Beads lifecycle workflows with real Go and Odoo verification, existing association retries, native conflicts, and foundation-only portable evidence retrieval. |

The five initial lifecycle tests failed before implementation. The first full
suite passed 288 tests; final coverage adds an interrupted-write timeout case.
The focused suite also verifies cancellation after process start, malformed and
oversized write responses, foreign references, flag-like literal input, and
successful mutations followed by evidence-storage failure. No new dependencies,
foundation logic, generic permissions or orchestration abstractions were added.

Supported deployment remains Beads 1.3.2 embedded Git workspaces on Linux. Beads
owns native claim and guard behavior; simultaneous embedded writers and server
mode are not certified. Unknown write outcomes require inspection before a manual
retry. Creation and commenting do not acquire an exactly-once guarantee. Evidence
association retains its tested idempotent reference behavior. Normal lifecycle
access and restricted inspection use the same existing operator policy with
separate command grants. Operators must renew exact-version or wheel trust for
`devkit-beads` 0.2.0. The next useful step is a selected repository pilot; strict
filesystem read-only operation is no longer a roadmap prerequisite.

## Proposed v0.7 — everyday verification and linked worktrees

The [repository assessment and acceptance design](v0.7_Assessment.md) separates
verified native Beads behavior from adapter support. Start with small foundation
improvements; do not expand Odoo or introduce orchestration.

| Order | Independently testable slice | Completion evidence |
| --- | --- | --- |
| 1 | Shell child-check diagnostics and installed type annotations | Implemented during assessment; CLI regression and isolated typed-consumer acceptance |
| 2 | Find evidence by exact reference with existing `RunStore` metadata | Scoped list/filter, pagination, corrupt metadata, retained families and foundation-only tests |
| 3 | Linked-worktree adapter compatibility | Native identity and registered Git topology validation, exact checkout grants, provenance, transport parity, retention and contention gates; current protections remain until satisfied |
| 4 | Plugin publication readiness | Decide distribution ownership, license and compatibility policy; package metadata and independent build/type/runtime matrix |
| 5 | Direct server/concurrency qualification if needed | Pinned isolated server, competing claims, guarded updates, timeout/cancellation/restart tests; shared/proxied modes remain separate |

The repeatable non-Odoo workflow is in `scripts/check_beads_workflow.py`, called
by the installed-wheel gate. It exercises failing verification, repair, evidence
association/review, explicit closure and retention. Native `git worktree add` and
`bd worktree create` share the same ledger in sequential probes; the adapter still
rejects both. No source or result schema changes are required for the small fixes.

Assessment verification: 291 tests passed in 86.44 seconds; Ruff lint/format,
strict mypy and import boundaries passed. The full installed-wheel matrix passed
in 13 environments, including the new repair/worktree probes and installed
consumer typing. See the assessment's verification record for commands and limits.
The marker fix followed a reproduced `import-untyped` failure; the CLI regression
also failed before its fix. Server and simultaneous-writer acceptance remain
unimplemented, and existing workspace guards are unchanged.

### v0.7 reference discovery implementation

`RunStore.list` gains an optional exact reference filter, exposed as
`runs list --reference`. Reuse the locked scan, project selection, reference
metadata, reserved `work_item_ref`, stable sort and pagination. The CLI applies
pin-compatible redaction. Filtering happens before pagination, and the response
schema is unchanged. Operator-only access, plugin independence and fail-closed
corrupt metadata handling remain intact. No index or provider-specific parsing
is needed. Existing retention code is unchanged.

Tests exercise arbitrary Unicode reference text, exact matching, duplicate pins,
project isolation, explicit all-project scope, pagination, missing matches,
corrupt metadata in either project and retention after filtering. Installed-wheel
acceptance uninstalls Beads before querying its existing association, and queries
copied evidence in a foundation-only installation. The new CLI tests failed
before the implementation. Baseline complexity passed at threshold 10; no
unrelated cleanup is required.

Reference slice verification: 294 pytest tests passed in 86.75 seconds. Ruff
lint/format/complexity, strict mypy and import boundaries passed. The full
13-environment installed-wheel gate passed, including actual Beads uninstallation
and foundation-only filtered retrieval. Changed functions remain below complexity
10 (`RunStore.list`: 2, CLI dispatch: 5).

### v0.7 sequential linked worktrees design

Reuse the adapter's bounded subprocess supervisor, native `bd context`, existing
per-checkout command grants and `RunStore` project scope. Add a private topology
module inside the adapter to validate supervised Git plumbing, registered
worktree paths and the administrative backlink. Native discovery runs without
ambient `BEADS_DIR`; subsequent calls bind to the verified main `.beads` directory.
Compare native checkout/root paths and UUID, and repeat validation before writes.
This deep module hides topology details without changing the specialization
contract or adding core lifecycle behavior. No new dependency is needed.

Support a normal main checkout and linked checkouts sequentially, including a
linked checkout without local `.beads` metadata. Reject bare/detached-Git-directory
topologies, unregistered or forged paths, symlink escapes, external redirects,
server modes and identity changes before mutation. Detached HEAD within a properly
registered worktree is not an unsupported topology. Evidence and configuration
stay on the invoking checkout. Association remains same-checkout-only even when
issues share a UUID. Bump `devkit-beads` to 0.3.0 and renew exact-version trust.

Tests will use actual Git repositories with controlled Beads responses for
adversarial topology/identity/cancellation cases, plus installed Beads 1.3.2 in a
main checkout and two linked worktrees. Exercise native lifecycle, distinct
verification revisions, grants and cross-checkout denials, association retries,
reference filtering, retention and all invocation surfaces. Simultaneous writers
remain explicitly unqualified; do not add a Devkit lock or scheduler. Native Git
and Beads remain trusted executables; checks do not eliminate hostile filesystem
races. Baseline complexity passes; no unrelated refactor is needed.

Sequential-worktree verification: `.venv/bin/ruff check .`,
`.venv/bin/ruff format --check .`, `.venv/bin/mypy` and `.venv/bin/lint-imports`
passed. Final `.venv/bin/pytest -q`: 311 passed in 98.69 seconds. The full
`DEVKIT_BEADS_BINARY=/tmp/devkit-beads-1.3.2/bd .venv/bin/python scripts/check_wheels.py`
gate passed across 13 independent environments, including renewed adapter trust,
main + two linked checkouts, separate revisions/grants/evidence, successful and
denied association on CLI/Python/MCP, native lifecycle, retention and uninstall
regressions. The changed adapter functions stay at complexity 8 or below, against
the existing limit of 10. The isolated workflow also passed before the full gate.
No concurrent-writer or server compatibility is claimed. Reference-slice hosted
checks and CI pilot both passed on `42d52b7`.

## v0.8 design: independent authors and onboarding

Reuse entry-point discovery, activation validation, exact operator trust and
artifact pins, `create_service(...).execute(...)`, `CommandResult`/`CommandSpec`,
RunStore and the existing CLI/Python/MCP wheel matrix. Core contract tests already
cover invalid registrations, schemas, results, cancellation and policy failures.
The current independent test builds a renamed distribution but supplies its
implementation and test harness from this repository. The template itself has
no tests, README or configuration examples, while repository-local contract
helpers construct internal settings/policy objects.

Move the existing bounded README check into the template as its useful command;
remove the duplicate standalone implementation. Supply self-contained tests that
exercise an installed plugin through `devkit.app.create_service` and isolated
operator/project configuration. Use ordinary pytest as a development dependency,
not a core runtime dependency. Document the small public Python entry point and
contracts used by those tests. A testing SDK is not justified if this succeeds.

Extend the existing clean-room script to copy/rename the complete template,
build from its sdist, install only wheel artifacts, and run its own tests with
isolated Python and no repository imports. Instrument the acceptance copy to
prove discovery and untrusted selection do not import code. Preserve unrelated
plugin and historical evidence checks. Expand transport scenarios to invalid
input and denial without duplicating the foundation's internal contract suite.

At the CLI seam, retain metadata-only `plugins list` and add optional project
selection/trust details without implying activation or artifact verification.
Reuse `doctor` for actionable `plugins validate` failures. Keep policy and
activation separate; installation never edits policy. Add package README,
description and source metadata, validate wheel/sdist contents, and document
public compatibility, supported baseline and owner-only publication decisions.
No license or registry ownership will be selected or published by this work.

Compatibility: plugin API 1.0 and evidence 1.0 remain unchanged. Template command
changes affect the unpublished example distribution only and will use its next
version. Any CLI inspection fields are additive; default metadata discovery
continues to work with invalid project configuration. Only documented contracts
and invocation entry points receive compatibility promises; constructors and
private validation/policy modules do not. Local artifact trust remains unchanged.

Acceptance: red/green tests for concrete diagnostics, template-owned tests against
independent wheels, entry-point/metadata and sdist rebuild validation, all three
surfaces, no-import trust checks, deactivation/removal, foundation/domain/Beads
regressions and existing full gates. Complexity stays at 10. No speculative
marketplace, installer, registry rewrite, runtime dependency or orchestration is
needed. Publication licensing/naming decisions remain owner approvals.

### v0.8 delivered and verified

Implemented with foundation 0.1.3 and template 0.2.0. Plugin API 1.0,
result/evidence envelope 1.0 and existing specialization commands are unchanged.

- The canonical template now supplies the bounded README validator, schemas,
  explicit effects/surfaces, an optional check, project/operator examples, build
  instructions and 14 self-contained installed-package tests. The duplicate
  standalone implementation was removed. The fixture uses the public service
  entry point; no test SDK, internal source imports or runtime dependency was added.
- The clean-room exercise renames the complete template, builds its sdist,
  rebuilds/installs its wheel and runs its own tests outside the monorepo under
  isolated Python. Import markers establish metadata-only discovery and rejection
  before import for untrusted selection. Trust without a grant remains denied.
  Success, defect, invalid input and denial agree across CLI/Python/MCP. Removal
  preserves the unrelated installed plugin and historical evidence.
- Metadata inspection optionally reports project selection, missing packages and
  configured trust. It explicitly does not verify pins or attempt activation.
  `plugins validate` now uses doctor's blocked activation diagnostics; its exit
  code for untrusted activation is 2 instead of the previous generic error 3.
  Existing command statuses/reasons and invocation authorization are unchanged.
  Denied-command summaries explain the policy fields to inspect.
- All six distributions have package descriptions and Markdown READMEs. Acceptance
  validates metadata and rebuilds each wheel from an independently extracted sdist,
  comparing payloads. Public interface, versioning and qualification limits are
  documented in [Compatibility.md](Compatibility.md). Developer/operator and
  author paths are in [Getting_Started.md](Getting_Started.md) and
  [Plugin_Authoring.md](Plugin_Authoring.md).

The service remains the module owning command validation, authorization and
evidence; the CLI inspection change only presents existing configuration and
metadata. No additional permission model or plugin abstraction was needed.
The moved validator's alternate-filename diagnostic initially still named
README.md; a failing regression established the problem and the diagnostic now
names the requested file. The three initial CLI diagnostic tests also failed
before implementation. No unrelated cleanup or domain behavior was changed.

Executed on November 1, 2026, Linux/Python 3.12:

| Command / exercise | Observed result |
| --- | --- |
| `.venv/bin/ruff check .` | Passed, including configured McCabe limit 10. |
| `.venv/bin/ruff format --check .` | Passed, 140 Python files formatted. |
| `.venv/bin/mypy` | Passed, 31 runtime source files under strict checking. |
| `.venv/bin/lint-imports` | Passed; foundation optional-integration boundary kept. |
| `.venv/bin/pytest -q` | 320 passed in 97.39 seconds. |
| `DEVKIT_BEADS_BINARY=/tmp/devkit-beads-1.3.2/bd .venv/bin/python scripts/check_wheels.py` | Passed full 13-environment matrix, including foundation-only, domain-only, real Beads lifecycle and sequential linked worktrees. |
| Same matrix: independent authoring | 14 template-owned tests passed; renamed sdist/wheel, installed type-consumer checks, all transports, denial, removal and historical evidence passed. |
| Same matrix: packaging | All six metadata inventories and independent sdist rebuilds passed with identical wheel payloads apart from RECORD. |
| Literal MCP example from the author guide | Executed successfully from an external installed-wheel environment; Python/MCP results and stored evidence matched. |
| Local links in changed Markdown | 61 file targets resolved. |

Changed-function complexity was inspected separately with Ruff's threshold lowered
for reporting: CLI dispatch 9, result renderer 6, plugin renderer 5, configuration
inspection/trust helpers 3, invocation policy branch 6, template handler 4 and
package validation 4. No changed function exceeds 10. The existing handler
supervision function remains at 10 and was not expanded.

Deferred owner decisions: choose distribution/import/CLI naming because PyPI's
`devkit` belongs to a different project; select a license and approve release
ownership/provenance. No registry claim, public release or publication was made.
Package metadata intentionally omits an unapproved license. Local wheel-based
authoring is verified; public distribution readiness is conditional on those
decisions. Newer Python/platforms and the full declared dependency ranges remain
unqualified; sequential Beads worktrees do not establish concurrent writer safety.

Recommended v0.9 priority: resolve owner naming/licensing decisions, then qualify
the supported Python and dependency range with installed-artifact CI. Prepare a
reviewable release/provenance procedure after those decisions. Keep additional
specializations, orchestration and concurrent Beads support out of that scope.

### Approved naming and licensing migration

Reuse the existing native Python packaging, entry-point discovery, operator trust,
RunStore and installed-wheel matrix. The owner selected the existing McCann Hub
convention: `mccann-hub-devkit` distributions and `mccann_hub.devkit` imports, with
sibling specializations such as `mccann_hub.devkit_go`. The outer `mccann_hub`
directory is a native namespace package without an `__init__.py`, matching the
owner's existing published packages. GPL-3.0-or-later is approved for this project,
its specializations and its copyable template.

Move the import packages and registration group together; all command behavior
stays in CommandService. Foundation 0.2.0 records this prepublication Python/package
name break. Plugin API and evidence schema remain 1.0. Existing command IDs, CLI
executables, devkit.toml, XDG paths and references remain unchanged. Do not add a
top-level devkit compatibility shim: that would preserve the import collision.
Operators explicitly replace old distribution trust keys and wheel pins; no grants
or trust are migrated automatically. Rebuild external plugins against the renamed
foundation. Old environments can remain isolated while migration is tested.

Ship the unmodified GPLv3 text plus explicit or-later notices and SPDX metadata in
every wheel/sdist. Package copies of the license are necessary so each distribution
and the template can build independently. Existing provenance records describe a
fresh implementation and synthetic fixtures; repository inspection alone cannot
establish legal title. Preserve dependency and upstream notices where applicable.

Tests will cover namespaced wheel contents, coexistence with unrelated namespace
siblings and a top-level devkit module, rejection of old trust keys, independent
authoring, retained pre-migration evidence/references and all existing gates.
Baseline Ruff, including complexity <=10, passed before changes. This is a public
packaging migration, not a registry or authorization redesign. No unrelated files
or the untracked .serena directory are part of the work.
