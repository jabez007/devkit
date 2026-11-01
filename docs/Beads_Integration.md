# Beads work items and verification evidence

`devkit-beads` 0.3.0 is an optional specialization requiring foundation 0.1.2.
It supports ordinary task lifecycle operations and explicit evidence associations.
Beads owns readiness, dependencies, claims, task status and closure rules. Devkit
provides separately authorized commands and verification evidence. The v0.6
inspection-only scope was an initial release choice, not an architectural rule.
Trusted developers and authorized agents can use the same commands.

## Supported environment

The supported profile is Linux with Python 3.12+ and **Beads 1.3.2**, using an
initialized embedded Dolt workspace in a normal main Git checkout. Registered
linked worktrees share that ledger and are supported for sequential operation.
The tested upstream revision is
[`9b65b9e198acbcc98e7fd3a87a5d55baa065a572`](https://github.com/gastownhall/beads/tree/9b65b9e198acbcc98e7fd3a87a5d55baa065a572).
Other Beads versions, server modes, redirects, bare repositories, separate Git
directories and symlinked workspace paths remain blocked. Devkit does not install
or initialize Beads, start servers or request administrative migrations.
Ordinary writes retain native Beads hooks, maintenance and schema behavior.

### Linked checkouts

Create worktrees with native `git worktree add` or `bd worktree create`. Initialize
Beads once in the main checkout. Linked checkouts may contain tracked `.beads`
metadata or omit that directory. Do not create a separate ledger per checkout.
Native Beads discovery must select the main checkout's ledger in either case.

Use `--project /absolute/path/to/linked-checkout`. Keep its `devkit.toml` and check
profile in that checkout. Add each checkout's canonical path explicitly to the
existing operator profile's `projects` list. A grant for the main checkout never
authorizes its siblings. Restricted inspection uses the same command omissions
as in the main checkout.

The adapter validates Git's common directory, registered paths and administrative
backlink. It compares Beads' main root, checkout root and ledger location with
that topology, binds calls to the shared `.beads`, and rechecks identity before
writes. Ambient `BEADS_DIR` and Git environment overrides are not inherited.
An identity change before execution blocks the write without claiming a mutation.
Git and Beads are trusted executables; these checks do not eliminate hostile
filesystem races.

Workspace results retain their existing fields and add `checkout_root`,
`workspace_root` (the main checkout), `is_worktree`, and
`concurrency="sequential-only"`. These are additive command data; plugin API 1.0
and evidence envelope 1.0 are unchanged. Each verification run retains its own
checkout path and Git revision. Sharing a Beads UUID does not broaden evidence
access: association accepts only a run from the invoking checkout. Use explicit
`runs list --reference ... --all-projects` for operator-wide discovery.

Simultaneous writers are **unqualified**. Devkit neither detects nor serializes
overlapping Beads invocations and adds no new lock service. Run this supported
workflow sequentially. Claim and guard behavior still belongs to Beads; successful
sequential tests do not establish concurrent-writer safety.

Install the foundation and adapter wheels from this checkout into your chosen
environment. Install the official [Beads 1.3.2 release](https://github.com/gastownhall/beads/releases/tag/v1.3.2)
separately and make its `bd` executable available on PATH. The Python adapter does
not download tools or require Odoo, Go, Docker, or an agent.

```sh
uv build --all-packages
uv pip install --python /path/to/venv/bin/python \
  dist/devkit-0.1.2-py3-none-any.whl dist/devkit_beads-0.3.0-py3-none-any.whl
```

Select `beads` in `devkit.toml`, alongside the specialization whose checks you
need. [The Go example](../examples/beads/devkit.toml) selects `go.tests` as its
verification profile. For Odoo, select `odoo` and `odoo.manifests` instead. This
integration adds no domain checks and does not change what a verification proves.

Merge [the policy example](../examples/beads/policy.toml) into the external
operator policy. Replace the project path, retain only needed surfaces, and set
mode `0600`. Exact distribution trust and command grants are separate; existing
wheel-hash pinning also applies. Every item command needs the `beads.workspace`
prerequisite grant on the same invocation surface. `doctor` checks that
prerequisite through the existing registry.

Read commands declare `read_fs`, `write_fs`, `execute_process`, and conservatively
`network_read`. The `write_fs` grant covers observed embedded Dolt bookkeeping:
its reads rewrite internal files with identical bytes and changed mtimes, even
under Beads `--readonly`. Work-item data, workspace configuration, and the
last-touched marker remain unchanged in acceptance tests. This bookkeeping is an expected filesystem effect, not a restriction on normal
task lifecycle operations. Optional restricted access means no task mutations;
it does not promise zero filesystem writes.
`network_read` is declared because Beads configuration can select a remote
backend before the adapter can inspect and reject that mode. Association also
uses `write_fs` for the Devkit reference store. All invocations produce Devkit
evidence as usual.
Inspection and association use `--readonly --sandbox --json` queries. Lifecycle
commands use `--sandbox --json --actor=...` and require all five effects, including
`network_write`, because native writes can run configured hooks or maintenance.
`--sandbox` suppresses automatic Dolt pushes. It does not isolate the executable
or disable every Beads maintenance operation. Item lookup
uses `list --id` with inclusion flags and a two-row limit, then validates the
exact returned ID. It deliberately avoids Beads 1.3.2 `show`, which writes the
last-touched marker even in read-only mode. The child environment binds the validated shared workspace and disables metrics with
`BD_DISABLE_METRICS=1`. Policy grants and Beads flags do not isolate arbitrary
third-party executable code; use trusted tool installations.

## Normal and restricted access

To find associated evidence without loading Beads, use
`devkit --project /path/to/checkout runs list --reference 'beads:<project-uuid>:<issue-id>'`.
This also works after uninstalling the adapter. Add `--all-projects` explicitly
to search the operator's entire local evidence store.

The single [operator policy example](../examples/beads/policy.toml) lists separate
grants for inspection, local evidence association, and five lifecycle commands.
Renew exact-version trust for `devkit-beads="0.3.0"`. Earlier adapter-version trust fails
closed after upgrading. If you pin a wheel, update its path and hash as well.

For normal development, retain the lifecycle grants needed by the developer or
agent. For restricted inspection, omit `beads.item.create`, `beads.item.claim`,
`beads.item.update`, `beads.item.comment`, and `beads.item.close`. Keep
`beads.evidence.associate` if local evidence pinning is wanted. An existing scoped
`deny` can revoke any command. A `write_fs` grant on an inspection command does
not authorize a different command. No new profile, permission model, or
repository-controlled read-only switch is involved.

Administrative commands such as delete, purge, migration, backup restore,
force-close and force-reassignment are not exposed. Ordinary update cannot set
assignee or close a task; claim and close have separate grants. There is no
arbitrary CLI passthrough. Any future administrative capability needs its own
explicit command grant. This restriction does not change Beads' native internal
maintenance behavior when an ordinary write runs.

## Commands

| Command | Arguments | Successful data |
| --- | --- | --- |
| `beads.workspace` | None | Workspace project UUID, tool version, backend and mode. |
| `beads.item.show` | `ref` | Workspace and item with qualified reference, title, description, status, type and priority. |
| `beads.ready` | Optional `limit`, 1–100, default 20 | Workspace, ready items, limit and `possibly_truncated`. Beads defines readiness and default filtering. |
| `beads.dependencies` | `ref` | Direct outgoing relationships with qualified references and dependency types. This is not a transitive dependency solver. |
| `beads.evidence.associate` | `ref`, `run_id` | Existing run ID, reference set, workspace and original verification status. |

Every lifecycle command requires `actor`, an explicit Beads audit label. It is not
an authenticated identity or an additional authorization mechanism. Trusted
callers choose an appropriate human or agent label. Beads applies its own actor
normalization and claim rules. Item results now include native `assignee`,
`created_by`, and `close_reason` when present. These are additive data fields;
the plugin and evidence schema versions remain unchanged.

| Lifecycle command | Additional arguments | Native Beads operation |
| --- | --- | --- |
| `beads.item.create` | Required `title`; optional `description`, `type`, `priority`, qualified `ref` | `create`, with optional explicit ID for later reconciliation. |
| `beads.item.claim` | `ref` | `update --claim`; Beads atomically claims and rejects incompatible ownership. |
| `beads.item.update` | `ref` and at least one of `title`, `description`, `priority`, `status`; optional `if_status`, `if_assignee` | `update` with native guards. Status accepts open, in_progress, blocked, deferred. |
| `beads.item.comment` | `ref`, `text` | `comments add` with the exact supplied text. |
| `beads.item.close` | `ref`, `reason` | `close`, respecting Beads blockers and closure policy. |

No force flags or automatic next-task selection are accepted. Updates assign
literal values, not shell fragments. Claims and leases follow Beads' rules;
Devkit does not renew leases in the background or schedule work.

References are `beads:<project UUID>:<issue ID>`. The project UUID comes from
`bd context --json`, not from an absolute filesystem path or issue prefix. Copy a
reference from `beads.ready` or construct it using `beads.workspace`. A reference
from another project is rejected, even when its issue ID exists locally. Copying
a Beads workspace preserves its identity; Devkit does not mint an independent
identity for a copied work graph.

```sh
devkit --project /path/to/project --json doctor
devkit --project /path/to/project --json run beads.workspace
devkit --project /path/to/project --json run beads.ready --args '{"limit":10}'
devkit --project /path/to/project --json run beads.item.show \
  --args '{"ref":"beads:<project UUID>:<issue ID>"}'
devkit --project /path/to/project --json check verify
# Use the existing verification run_id from the preceding envelope:
devkit --project /path/to/project --json run beads.evidence.associate \
  --args '{"ref":"beads:<project UUID>:<issue ID>","run_id":"<run UUID>"}'
devkit --project /path/to/project --json runs show '<run UUID>'
```

Python uses `create_service(Path(project)).execute(command, arguments)`. The
optional MCP adapter exposes these same commands when authorized. Both preserve
CLI authorization, validation, cancellation and result semantics.

## Writable development workflow

Use the same project and external policy for CLI, Python, or MCP. Only authorized
commands appear in MCP discovery. The following requests deliberately change
Beads state. Substitute actual qualified references from returned results:

```sh
devkit --project /path/to/project --json run beads.item.create \
  --args '{"actor":"developer","title":"Improve verification","type":"task"}'
devkit --project /path/to/project --json run beads.item.claim \
  --args '{"actor":"developer","ref":"beads:<project UUID>:<issue ID>"}'
devkit --project /path/to/project --json run beads.item.update \
  --args '{"actor":"developer","ref":"beads:<project UUID>:<issue ID>","priority":1,"if_status":"in_progress"}'
devkit --project /path/to/project --json check verify
devkit --project /path/to/project --json run beads.evidence.associate \
  --args '{"ref":"beads:<project UUID>:<issue ID>","run_id":"<verification run UUID>"}'
devkit --project /path/to/project --json run beads.item.comment \
  --args '{"actor":"developer","ref":"beads:<project UUID>:<issue ID>","text":"Reviewed the linked verification evidence."}'
devkit --project /path/to/project --json run beads.item.close \
  --args '{"actor":"developer","ref":"beads:<project UUID>:<issue ID>","reason":"Verification reviewed"}'
```

Run verification when appropriate for the work, then explicitly request any
comment or closure. Association never posts a comment or closes an item. A
successful check is evidence for a decision, not automatic approval.

### Write outcomes and retries

Devkit issues each mutation once. It does not replay writes after failures.
Beads owns claim idempotence and update guards. A stale update guard returns
blocked `BEADS_CONFLICT`; inspect current state before choosing another update.
A denied command, invalid input, or failed workspace prerequisite never reaches
the mutation process.

Nonzero write exits, malformed responses and excessive output return
`BEADS_WRITE_UNCERTAIN` with `mutation_may_have_occurred: true`. A refusal can
share this conservative result with a post-write failure because the adapter
does not infer task state from stderr text. Inspect the item with
`beads.item.show` or native Beads commands before retrying. Cancellation and
timeout also do not prove a write was rolled back. The shared invocation service
may return `CANCELLED` or `TIMEOUT` after a task change has already taken effect.

Creation with a generated ID and comment addition are not idempotent. Inspect
native `bd list --readonly --json` or `bd comments ID --readonly --json` after an
uncertain result. An explicitly supplied create `ref` gives a stable lookup key,
not an adapter-owned deduplication guarantee. Beads decides whether that ID is
available. If Devkit's evidence write fails after a confirmed mutation,
`EVIDENCE_WRITE_FAILED` retains `observed_result`, including the returned item or
comment identifier. This local evidence failure is not a reason to repeat the
external write automatically. Evidence association has the stronger idempotent
reference semantics described below.

## Association, retention, and portability

Association checks a completed run in the selected project and retrieves the
live Beads item before adding its qualified reference with `RunStore.reference`.
Runs with failed, blocked, or error outcomes may be associated; the returned
`verification_status` preserves that outcome. Association success means that the
local link was recorded. It does not mean the verification passed or the task
was approved. The original `result.json` remains unchanged, including the reserved
`work_item_ref: null` field. References live in the existing `references.json`.
Plugin API 1.0 and evidence envelope 1.0 are unchanged.

Repeat the same request safely: references form a set. A missing item, missing
run, inaccessible store, or foreign-project run cannot produce a successful link.
Concurrent pruning can remove an unpinned run before association; reference
creation revalidates under the store lock and then fails explicitly. Retry after
resolving the reported error. If invocation evidence fails *after* the reference
is saved, `EVIDENCE_WRITE_FAILED` includes the `observed_result`; inspect the run
or retry the same association. No external comment or duplicate Beads record is
created in either case. Cancellation near persistence can leave the local
reference saved; inspect it before deciding whether to retry or remove it.

Existing retention protects referenced runs and related aggregate evidence.
Retrieve references with `runs show` or `runs list`, even after deactivating or
uninstalling the Beads adapter. References remain until an operator explicitly
removes them with `runs unpin RUN_ID --reference REF`. Closing or deleting a Beads
issue does not automatically remove its evidence protection.

For portable evidence, copy the run directories under the Devkit state root's
`runs/`, including `result.json`, `references.json`, and related parent/child runs.
Read copies with `runs show RUN_ID --all-projects` in a foundation-only install;
original project paths and UUIDs remain intact. Local pins cannot control a CI
provider's artifact expiry. Evidence contains project and work-item information:
choose the destination and its retention policy deliberately. There is no new
archive format, remote evidence service, or live synchronization mechanism.

## Diagnostics and limits

`MISSING_TOOL`, `BEADS_NOT_INITIALIZED`, `UNSUPPORTED_BEADS_VERSION`,
`UNSUPPORTED_BEADS_WORKSPACE`, `BEADS_ITEM_UNAVAILABLE`, and
`WORKSPACE_MISMATCH` explain unavailable
coverage. Nonzero Beads exits return blocked `BEADS_UNAVAILABLE`; this adapter
does not guess whether an item is missing, the database is locked, or access was
denied from unstable stderr text. Malformed JSON or invalid records return error
`INVALID_TOOL_OUTPUT`; excessive output returns error `OUTPUT_LIMIT`. Each stream
is bounded to 256 KiB. Deadlines and cancellation use the foundation supervisor.
Raw stdout/stderr are not copied into evidence. No Beads writes are used to repair
an unavailable workspace.

An environment prerequisite failure appears under the parent result's
`data.checks`, with separate child evidence and its specific reason. `doctor`
reports prerequisites, not a successful software verification. Issue data reflects
the time it was retrieved; associations do not continually refresh task status.
Concurrent Beads writers, remote servers, redirected worktrees, and other Beads
versions are unverified. Static Odoo validation remains distinct from runtime
installation or compatibility.

## Reproduce acceptance

The wheel matrix requires an explicit test-tool path. It creates and deletes
only disposable synthetic workspaces and never initializes this repository.
Download the official Linux amd64 release into a temporary directory, check the
archive SHA-256 below, and extract its `bd` member:

```text
c6ea3281f6ff82628351b2d0967c9eb85862c8a0ec0ebc24e63e645c8b02462e
```

Then run:

```sh
DEVKIT_BEADS_BINARY=/absolute/temporary/path/bd uv run python scripts/check_wheels.py
```

[CI](../.github/workflows/checks.yml) records the exact download and checksum
commands. The matrix uses real Beads 1.3.2 with Go and Odoo. It checks inspection-state preservation, explicit lifecycle writes and native conflicts, association on CLI/Python/MCP, idempotent repetition,
retention protection, and foundation-only retrieval of copied evidence. The
unit/integration suite adds controlled missing-tool, malformed-output,
policy-denial, cancellation, and partial-failure cases. Synthetic fixtures do not
establish production deployment or simultaneous embedded-writer compatibility.
