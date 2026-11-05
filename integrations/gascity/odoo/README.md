# Deliver an approved Odoo task

This pack takes an explicitly selected local bead through a behavior brief,
human approval, a test plan and at most three red implementation attempts.
Gas City owns the graph and retries. Devkit owns its checks and evidence.
The pack has no tracker client and does not use Devkit's embedded-only Beads
adapter against Gas City's server workspace.

## Prepare the project and tools

Use the pinned native tools and [shared session preparation](../README.md).
Import this directory under the binding `odoo`. Its relative `base` import
provides `devkit-claude` and the brief commands. Keep the two directories in
the same reviewed checkout. The formula extends `devkit-approved-brief`.

Build the project's devcontainer with these tools:

- Python 3.12, Git, `devkit` and `devkit-odoo` from the reviewed 0.7.0 Odoo
  distribution and its compatible foundation distribution.
- Native Odoo 19, its dependencies, and PostgreSQL client tools `psql`,
  `createdb` and `dropdb` for the runtime gate.
- The shared guard's pinned parser and the native session tools described
  in the [base guide](../README.md). The subscription credential file is a
  separate read-only mount.

Provide PostgreSQL connection variables through the operator's container
configuration. The database role needs `CREATEDB`. Devkit creates and removes
only its own disposable databases. See [runtime authorization and evidence](../../../docs/Odoo_Validation.md#run-native-odoo-tests).
Do not mount the Docker socket into the implementation session.

Create the per-task branch with `gc worktree ensure --agent odoo.implementer`
and the reviewed repository, base commit and absolute worktree path. Record
that path as `gc.work_dir` on the workflow root. The default implementer
directory is `CITY/worktrees/task`. For another path, patch the imported
agent's `work_dir` in the operator's city configuration before starting it.
Configure a Git author and signing behavior for the project before launching.
The session has no home Git configuration mount. The guard rejects inline Git
`-c` options and `GIT_*` environment overrides; ordinary commits use the
operator-prepared repository configuration.

Select the Odoo plugin in the task's `devkit.toml`. In operator-owned policy,
trust the reviewed Odoo distribution and grant these commands for the exact
canonical worktree path on the `cli` surface:

| Command | Effects |
|---|---|
| `odoo.module.version.check` | `read_fs`, `write_fs`, `execute_process` |
| `odoo.module.test` | `read_fs`, `write_fs`, `execute_process`, `network_read`, `network_write` |

Mount that policy read-only. A grant for the primary repository does not
authorize its linked worktree. Neither `bind` nor a pack issues grants.
Keep check artifacts and Devkit's `XDG_STATE_HOME` outside the Git worktree.

## Connect native Beads from the container

Beads 1.3.2 checks the local proxy's process identity before adopting it.
A container cannot adopt the host's PID record even with host networking.
Give it a native external-connection profile with its own container-local
proxy root. This connects to the same authoritative task database.

Keep the host proxy alive for the session, using the city's reviewed
`[beads] proxied_idle_timeout`. After warming it with a native task read, take
the `port` field from `CITY/.beads/dolt/proxy.pid`. Create a separate operator
profile, using that port in place of `12345`:

```json
{
  "root_path": "/tmp/devkit-beads-client-TASK",
  "external": {"host": "127.0.0.1", "port": 12345, "user": "root"},
  "idle_timeout": 0
}
```

This example uses the fixture's local loopback authentication. For another
server, use its reviewed native Beads authentication configuration. See the
pinned [profile schema](https://github.com/gastownhall/beads/blob/v1.3.2/internal/configfile/proxied_server_client_info.go)
and [external connection fields](https://github.com/gastownhall/beads/blob/v1.3.2/internal/configfile/external_dolt_config.go).

After shared preparation, append this read-only binding to the reviewed native
`GC_DOCKER_EXTRA` before applying the workspace environment:

```text
--mount=type=bind,src=/city/container-beads.json,dst=/city/.beads/proxied_server_client_info.json,readonly
```

Use the actual absolute city and profile paths. Keep the host's sidecar intact;
the binding changes only the container's view. Do not share host PIDs or mount
the Docker socket. The [live acceptance helper](../../../tests/gascity_live.py)
demonstrates this profile and checks native reads plus approval verification
inside the container before accepting the implementation run. Its final host
check observes the attempt closed through the same database.

Prepare a fresh profile if the host proxy restarts or changes ports. This
profile qualifies one local Linux host with host networking. Other connection
topologies need their own qualification.

## Bind one task and approve its brief

Run pack commands from the city directory. The pinned native CLI requires
`gc base brief` and `gc odoo delivery`; a leading `--city` reaches the pack
entrypoint as an argument and is not supported there.

Cook the selected bead once:

```sh
gc formula cook devkit-odoo-delivery --attach TASK \
  --var task=TASK --var brief_file=/city/brief.json --json
```

Keep its returned workflow root. Resume that root rather than cooking again.
Prepare an operator job JSON file with the full local base commit:

```json
{
  "project": "/city/worktrees/task",
  "base_commit": "0123456789012345678901234567890123456789",
  "addons_paths": ["addons"],
  "runner": ["devcontainer", "exec", "--workspace-folder", "/city/worktrees/task"],
  "artifacts": "/city/check-artifacts/task",
  "github": {
    "repo": "owner/test-repository",
    "remote": "origin",
    "base": "main",
    "head": "devkit/task",
    "protected_branches": ["release/*"]
  }
}
```

`runner` is an argv prefix, never shell text. An empty list uses installed
host commands. The project path must resolve to the same path inside the
runner's container, including the linked worktree's Git common directory.
Configure the project's devcontainer mounts accordingly. The operator starts
the container; the pack does not manage its lifecycle. Native gate commands
receive a restricted environment, so put required connection settings and
policy bindings in the container configuration, not only an interactive shell.

`github` may be omitted for local checks. Supply it before binding when the
workflow will publish. Binding is immutable for this workflow. The base and
protected branches are operator inputs. The publisher rejects those branches
and checks that the push remote names the selected GitHub repository.

Bind the job, write the brief using the inherited prompt, and record it:

```sh
gc odoo delivery bind /city/job.json --task TASK --workflow ROOT
gc base brief record /city/brief.json --task TASK --workflow ROOT
gc bd close BRIEF_STEP --reason 'Behavior brief recorded'
gc base brief show --workflow ROOT
gc base brief approve --workflow ROOT --sha256 REVIEWED_BRIEF_SHA256
```

Run `approve` as the operator with `DEVKIT_UNATTENDED` unset. It binds the exact
brief bytes to this task's native human gate. See the [behavior brief examples](examples/briefs/README.md).
Include known open questions in the brief. The draft report copies them.
Binding also starts the task's first feedback round on its actual Git branch.
A repeat bind can resume before the brief is recorded. A different active
workflow or branch stays blocked.

## Run and inspect the checks

Use the shared one-shot session configuration for `odoo.implementer`. Review
the session's tool allowlist, mounts and exact worktree policy before launch.
The native formula places the test-plan step after approval and implementation
after the plan. The agent commits a clean attempt and closes its native bead.
The native controller then invokes the pack check:

```sh
gc convoy control IMPLEMENT_CONTROL
```

For an operator diagnostic rerun, use `gc odoo delivery check --workflow ROOT`.
Only the native controller can settle the formula's implementation result.
A manual passing bundle does not override native failure or exhausted attempts.

Checks compare every changed addon with the exact base commit, require increased
explicit versions, and run `devkit-odoo --json --install-mode fresh` for each
changed addon. A static or version failure prevents runtime tests. If those
pass, `odoo.module.test` runs for every changed addon. A single configured
module or update mode cannot narrow the delivery gates. Ambiguous module names,
no changed addons, incomplete results, unavailable tools and authorization
failures stay blocked. Native semantic failures consume a red attempt;
infrastructure failures use Gas City's separate bounded infrastructure retry.

The pack saves private stdout, stderr and `results.json` under a new check
artifact directory. Each CLI result retains its Devkit run ID and evidence
path. A bundle passes only if its Git commit and clean state remain unchanged
during the checks. Review full runtime evidence for test counts and database
cleanup. The capture limit is 64 MiB per output stream and each command has a
ten-minute deadline. The JSON read limit is 1 MB.

## Review and publish the draft

After native checks pass, prepare the concrete text:

```sh
gc odoo delivery report --workflow ROOT
```

Review the returned title, body and `body_sha256`. The body includes the checked
commit, acceptance criteria, check results, selected task, approved brief hash
and open questions. Each recorded question includes its assumption and reason.
Later rounds include the answers that changed the brief. Runtime summaries
include test counts and database cleanup status. Local evidence paths remain
in the local check bundle. Each body revision has its own digest-named file;
preparing new text preserves the files you reviewed earlier.

Only after the operator approves this exact text, run:

```sh
gc odoo delivery publish --workflow ROOT --approved-body-sha256 REVIEWED_BODY_SHA256
```

Publication requires `DEVKIT_UNATTENDED` to be unset, a native passing
implementation result, the same clean commit and the selected GitHub remote.
It pushes that exact commit to the feature branch without force, creates a
draft with `gh pr create --draft --body-file`, then confirms its draft state,
commit and text through GitHub. It records the PR URL in native root metadata
and closes the draft step. The feedback metadata retains the PR URL on the
selected task. Repeating publication reuses an identical open draft. With a
known PR URL, new approved text updates that same open draft through
`gh pr edit --body-file`. A missing, unrelated, closed or ready PR stays
blocked. Approval of an earlier body cannot approve revised text.

## Continue after a person answers

Use the [shared feedback commands](../README.md#record-questions-answers-and-tool-friction)
to record questions and their assumptions on the task. The implementer writes
`questions.json` and imports it into the current native round. It writes tool
problems separately to `friction.json`. Import nonempty friction only into an
explicitly selected tooling bead. An empty array needs no tooling bead.

As the operator, record answers and prepare the proposed next brief:

```sh
gc base feedback answers /city/answers.json --task TASK --workflow ROOT --round 1
gc base feedback draft /city/round-two.json --task TASK --workflow ROOT --round 1
```

Review the proposal. Cook `devkit-odoo-delivery` once for the same task with
that file, retaining the new root and step IDs. Reuse the existing branch and
worktree. Then advance the round:

```sh
gc base feedback next /city/round-two.json --task TASK --workflow ROOT --round 1 \
  --next-workflow NEXT_ROOT
gc bd update NEXT_ROOT --set-metadata gc.work_dir=/city/worktrees/task
gc odoo delivery bind /city/round-two-job.json --task TASK --workflow NEXT_ROOT
```

The new immutable job uses the same project and GitHub destination. Select
the prior checked commit as its base and a live runner for this round's gates.
The new brief still needs its own exact-hash approval. Close its brief step
and approve it before starting the test plan and implementation. An older
approval does not release the new round. See the [round transition contract](../README.md#run-a-new-round-from-rejected-assumptions).

After the new native checks pass, report and review the new text. Publish only
with approval of that body's hash. The publisher pushes the checked commit
without force and updates the task's known draft PR.

## Run the acceptance case

The opt-in case uses real native Beads and Gas City, installed Devkit wheels,
Odoo 19 and PostgreSQL. It proves approval isolation, a red install-order
attempt, native retry and a passing runtime bundle before draft readiness:

```sh
DEVKIT_GASCITY_ACCEPTANCE=1 \
DEVKIT_GC=/absolute/pinned/gc \
DEVKIT_BD=/absolute/pinned/bd \
DEVKIT_DOLT=/absolute/pinned/dolt \
DEVKIT_GASCITY_SOURCE=/absolute/clean/gascity-source \
uv run pytest -q tests/test_gascity_odoo_acceptance.py
```

By default, this case drives synthetic implementation attempts through the
native graph. To have Claude fix and commit the second attempt inside the
project's built devcontainer, also set these variables:

```sh
DEVKIT_DELIVERY_LIVE=1
DEVKIT_DEVCONTAINER=/absolute/installed/devcontainer
DEVKIT_CLAUDE=/absolute/installed/claude
DEVKIT_CLAUDE_CREDENTIALS=/absolute/operator/.claude/.credentials.json
```

Export these variables or prefix the acceptance command with them. The live
variant uses the same native graph and installed Odoo checks. Its implementation
image uses the qualification fixture's devcontainer, and its full runtime gate
uses a separate Odoo container through the operator-selected runner. It tests
this explicit arrangement, not arbitrary devcontainer lifecycle commands.
Approval is performed by the fixture's synthetic operator. The case does not
publish to GitHub. The publisher contract tests use a scripted GitHub adapter.
Full GitHub acceptance uses the optional private repository target below and
explicit operator publication of the approved draft text.

## Prepare the private GitHub acceptance run

Create a dedicated private GitHub repository and set its canonical name alongside
the live acceptance variables above:

```sh
export DEVKIT_DELIVERY_GITHUB_REPO=owner/private-acceptance-repository
uv run pytest -q -s tests/test_gascity_odoo_acceptance.py \
  --basetemp=/tmp/devkit-github-acceptance-UNIQUE
```

Use a new base directory so the task state and review artifacts survive until
publication. Pytest deletes an existing `--basetemp` directory before running.
The repository must be private and have no pull requests. The case seeds an
empty repository's `main` branch. On a retry, it accepts an existing seed only
when its complete Git tree matches the synthetic fixture. It never force-pushes.

The case verifies that GitHub has no PR after the red install-order attempt.
After the live fix and passing checks, it pushes the exact checked commit to
the task's feature branch. It saves `operator-publication.json` under the
qualification root, containing the selected task, workflow, report, body hash
and the host environment needed to find the same native Beads state.

Review the report and approve its exact text before invoking the existing
`gc odoo delivery publish` command. The acceptance case does not create a PR or
treat its saved context as approval. Keep GitHub authentication in the operator's
host context when publishing, outside the implementation session.

The 2026-11-04 qualification completed this flow in a dedicated private
repository. Broken install order returned `INVALID_LOAD_ORDER` while GitHub
had no PR. The guarded Claude session fixed the addon, added a behavior test,
committed it and closed the native attempt. Version, fresh-install static and
native Odoo tests passed, with disposable database cleanup complete. After
the operator approved the exact generated text, the pack created a real draft
PR and verified its body, title and checked commit through GitHub. A repeated
publish returned the same URL, with one PR still present. Native Beads held
that URL and the draft step was closed. The fixture's brief approval remains
a synthetic operator action; this does not qualify a production approval UI.

To exercise a second live round against the retained private draft, export the
same native and live tool variables, then select the saved context explicitly:

```sh
DEVKIT_DELIVERY_RESUME_CONTEXT=/tmp/retained-qualification/operator-publication.json \
uv run pytest -q -s tests/test_gascity_live_round.py
```

This case imports a synthetic rejected label assumption, cooks one new workflow,
proves fresh approval is required, and runs Claude in the same worktree. It
checks the new commit with installed Odoo tools and pushes it to the existing
branch. It saves `operator-publication-round2.json` beside the original context.
The case verifies the original PR text is unchanged. Approve the new exact text
before updating the PR through the operator publisher.

The 2026-11-04 second-round qualification retained the first round's branch,
worktree and draft PR. Its new brief required a fresh approval. Claude changed
the menu label, increased the version and added a second behavior assertion.
Version, static and runtime checks passed, with two Odoo tests and complete
database cleanup. The retained-case verification passed after allowing GitHub
time to report the pushed head. On 2026-11-05 the operator approved the revised
text. The native publisher updated the same draft and verified its exact body,
title and checked commit. A repeated publication returned the same URL with
one PR present. The task and new workflow retained round 2 and that PR URL;
the new draft step was closed.

The model abbreviated parts of its friction report. The operator extracted
the eight failed commands and their exact output from the transcript for import
into a separate synthetic tooling bead. The first import added eight comments;
the second added zero. The prompt now explicitly requires complete commands
and output. This qualifies the importer, not unattended report completeness.
