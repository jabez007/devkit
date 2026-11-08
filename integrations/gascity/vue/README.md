# Deliver an approved Vue task

This pack takes an explicitly selected bead through a behavior brief, human
approval, a test plan and at most three red implementation attempts. Gas City
owns readiness and retries. The shared base owns task rounds, feedback and
exact-text draft publication. The Vue adapter owns the project's check tools.
Tracker connectors populate Beads separately; this pack has no tracker client.

## Prepare the project and devcontainer

Import this directory as `vue` alongside its relative `base` import. Use the
[pinned native tools and session setup](../README.md). The implementer is
`vue.implementer` and the formula is `devkit-vue-delivery`.

Select the directory containing the app's `package.json` as the task project.
It must declare `vue`, `vitest`, `eslint` and `vue-tsc` in `dependencies` or
`devDependencies`. Prepare its locked dependencies before binding the job.
The pack uses only `PROJECT/node_modules/.bin`; it never downloads a missing
tool or substitutes a global installation. Tools must resolve within this
project. This profile does not qualify Yarn PnP or separate workspace packages
whose tools live outside the selected project.

Build the project's devcontainer with these tools:

- A Node version supported by the project's locked tools and its package manager.
- Python 3.12, Git, tmux, jq and the shared guard's pinned `bashlex` dependency.
- The pinned native Gas City and Beads binaries, exposed at the same paths used
  by native hooks and commands.
- Browser binaries and system libraries matching the project's Playwright
  version when Playwright is declared or configured.

For the [locked fixture](../../../tests/fixtures/vue/package.json), use Node
24.15 or later in major 24, or a supported major from 26 onward. Its browser image is
`mcr.microsoft.com/playwright:v1.64.1-noble`, matching `@playwright/test` 1.64.1.
See the [Playwright Docker guide](https://playwright.dev/docs/docker) for that
version's browser and system-library arrangement. Install Python and the shared
guard in a dedicated virtual environment. Keep the final session's user and
home directory explicit. Prepare the app's dependencies as the operator.

When applying the prepared workspace environment, set `PATH` explicitly for
the container. Put the guard's Python virtual environment and selected native
binary directories before the system paths. Native sessions can inherit the
controller's host `PATH`; an absent virtual environment then makes the guard
fail closed. Set `GC_HOME` and the `XDG_CACHE_HOME`, `XDG_CONFIG_HOME` and
`XDG_STATE_HOME` paths to the owned directories mounted for the session.
The [live helper](../../../tests/gascity_live.py) applies this configuration and
probes an allowed read and a denied credential read. It also checks that the
selected subscription file is readable and that Claude can create its session
directory, without reading credential contents.

The fixture's image and live profile use UID 1000 and `/home/ubuntu/.claude`.
The pinned image assigns UID 1001 to `pwuser`. Match the selected numeric user
to the writable home and read-only credential binding. Another host UID needs
a corresponding reviewed image profile.

Use the shared preparation command with the built image, reviewed pack paths,
project settings and selected subscription credential file. Mount the pack,
settings and credential file read-only. Keep GitHub authentication in the host
operator context. The session needs no Docker socket or home-directory mount.
For local container task access, use the qualified native external-proxy profile
in the [connection guide](../odoo/README.md#connect-native-beads-from-the-container).
Refresh that profile after a host proxy restart.

Create a task worktree with `gc worktree ensure --agent vue.implementer`.
Configure its Git author and signing behavior before launch. Record its absolute
path as `gc.work_dir` on the workflow root. The default agent directory is
`CITY/worktrees/task`; patch the native agent configuration for another path.
The check runner must see this project at the same absolute path as the host.
Keep dependencies, caches and generated browser reports ignored by Git, and
keep check evidence outside the project.

## Bind the selected task and approve its brief

Run pack commands from the city directory without a leading `--city` argument.
Cook the selected task once and retain the returned root and step IDs:

```sh
gc formula cook devkit-vue-delivery --attach TASK \
  --var task=TASK --var brief_file=/city/brief.json --json
```

Prepare an operator-owned job file:

```json
{
  "project": "/city/worktrees/task",
  "runner": ["devcontainer", "exec", "--workspace-folder", "/city/worktrees/task"],
  "artifacts": "/city/check-artifacts/task",
  "github": {
    "repo": "owner/private-test-repository",
    "remote": "origin",
    "base": "main",
    "head": "devkit/task",
    "protected_branches": ["release/*"]
  }
}
```

`runner` is a reviewed argv prefix, not shell text. An empty list uses installed
host tools. Omit `github` for local check qualification. This binding is
immutable for the workflow and starts feedback round 1 on the actual branch.
The pack never changes Devkit trust or command grants. The operator explicitly
selects this native runner; the Node tools do not create Devkit run records.
Their raw output and parsed results are retained in the native check bundle.

```sh
gc vue delivery bind /city/job.json --task TASK --workflow ROOT
gc base brief record /city/brief.json --task TASK --workflow ROOT
gc bd close BRIEF_STEP --reason 'Behavior brief recorded'
gc base brief show --workflow ROOT
gc base brief approve --workflow ROOT --sha256 REVIEWED_BRIEF_SHA256
```

Approve exact brief bytes as the operator with `DEVKIT_UNATTENDED` unset.
The test-plan and implementation steps remain blocked until their dependencies
are satisfied. Start the guarded one-shot `vue.implementer` session only after
approval and the test plan. Give it the task, workflow, round number, assigned
attempt and artifact directory. The agent commits a clean attempt and closes
only that attempt. Advance its controller with `gc convoy control IMPLEMENT_CONTROL`.

## Inspect checks and prepare the draft

The adapter runs these project-local tools in order:

1. `vitest run` with a JSON report outside the project. Watch mode is disabled.
2. `eslint . --max-warnings 0` with a JSON report. The gate never passes `--fix`.
3. `vue-tsc --noEmit --pretty false`.
4. `playwright test --reporter=json` when the manifest declares `@playwright/test`
   or `playwright`. A Playwright config without that dependency stays blocked.

These commands follow the tools' [Vitest CLI](https://vitest.dev/guide/cli.html),
[ESLint CLI](https://eslint.org/docs/latest/use/command-line-interface),
[Vue type-checking](https://vuejs.org/guide/typescript/overview.html) and
[Playwright CLI](https://playwright.dev/docs/test-cli) interfaces.
Project configurations select tests and browser projects. The job cannot narrow
checks with ad hoc arguments. A red check stops subsequent gates. Missing tools,
malformed reports, empty test runs and infrastructure exit codes stay blocked.
Vitest and Playwright must execute at least one test. ESLint warnings fail the
gate. TypeScript exit codes 1 and 2 are project check failures; other nonzero
codes are infrastructure failures.

Every bundle records the exact clean commit, approved brief reference, argv,
exit codes and results. Each tool has a ten-minute deadline and a 64 MiB output
limit per stream. JSON reports have a 1 MB read limit. A changed or dirty
worktree invalidates the bundle. Inspect private `results.json`, stdout,
stderr and JSON reports in the returned artifact directory.

After native checks pass, prepare the text:

```sh
gc vue delivery report --workflow ROOT
```

Review its title, body and `body_sha256`. Only after approval of that exact
text, publish as the host operator:

```sh
gc vue delivery publish --workflow ROOT --approved-body-sha256 REVIEWED_BODY_SHA256
```

The publisher pushes the checked commit without force, confirms the draft's
body, title and head through GitHub, then closes the native draft step. Repeats
reuse the known draft. A later round needs a fresh brief approval and fresh PR
text approval. Use the [shared answer and friction commands](../README.md#record-questions-answers-and-tool-friction)
with the current workflow and round; the branch and PR reference stay on the task.

## Verify the pack

Run deterministic contracts without Node or containers:

```sh
uv run pytest -q tests/test_gascity_vue_checks.py tests/test_gascity_stack_neutral.py
```

The locked counter fixture starts with a behavior defect: one activation
increments the count twice. Its Vitest and keyboard browser tests specify one
increment. Live qualification must show a red native attempt, a committed fix,
passing installed tools and a real draft after exact-text approval. Contract
tests alone do not establish that result. The shared changes are listed in
[ADR 0001](../../../docs/adr/0001-delivery-loop-runs-on-gas-city.md#core-and-stack-packs).

Install the fixture's locked dependencies in a separate operator directory.
Keep its `package.json` beside `node_modules` so the case can compare the
declared versions. Then run the opt-in native case:

```sh
DEVKIT_VUE_ACCEPTANCE=1 \
DEVKIT_VUE_NODE_MODULES=/absolute/prepared-fixture/node_modules \
DEVKIT_GC=/absolute/pinned/gc \
DEVKIT_BD=/absolute/pinned/bd \
DEVKIT_DOLT=/absolute/pinned/dolt \
DEVKIT_GASCITY_SOURCE=/absolute/clean/gascity-source \
uv run pytest -q tests/test_gascity_vue_acceptance.py
```

This case needs Docker access. It uses the official browser image pinned by
digest in the test, and copies the prepared dependencies into its owned task
worktree. On 2026-11-05 it passed fresh-approval isolation, a native red retry
and all four installed tool gates. The final bundle recorded one passing
Vitest test and one passing Chromium keyboard test. The qualified browser
image ran Node 26.13.0. This case uses synthetic implementation commits and
stops before GitHub publication; it does not qualify live model behavior.

To run the guarded live implementation, also export:

```sh
DEVKIT_VUE_LIVE=1
DEVKIT_DEVCONTAINER=/absolute/installed/devcontainer
DEVKIT_CLAUDE=/absolute/installed/claude
DEVKIT_CLAUDE_CREDENTIALS=/absolute/operator/.claude/.credentials.json
```

For private GitHub qualification, set `DEVKIT_VUE_GITHUB_REPO=owner/private-test-repository`
and use a new `--basetemp=/tmp/devkit-vue-acceptance-UNIQUE` directory. Pytest
deletes an existing base directory. The fixture uses an isolated
`acceptance/vue-fixture-v2` base branch and a per-task feature branch. An
existing base must match the complete fixture tree; it is never overwritten
or force-pushed. Other branches and pull requests are outside this case.

After passing checks, the case pushes the checked feature commit and saves
`operator-publication-vue.json` with the report, body hash and safe host state
paths. It stops before creating the draft. Approve the exact title and body,
then publish through `gc vue delivery publish` in the retained city with host
GitHub authentication. The saved context is not approval.

The live 2026-11-05 case passed after aligning the numeric user and applying
the explicit container path and cache configuration above. The guard preflight
allowed a benign read and denied a credential read. The real one-shot Claude
session inspected the approved task, committed the counter fix and added
repeated pointer and keyboard activation tests. The controller passed two
Vitest tests, ESLint, vue-tsc and two Chromium Playwright tests. Native hooks
completed and the assigned attempt closed in the same Beads store. On
2026-11-08 the operator approved the exact draft text. The native publisher
created a private GitHub draft and confirmed its title, body and checked commit.
A repeated publication reused that draft. Native task metadata recorded the
PR URL and the draft step closed. This is one local Linux profile with synthetic
brief approval, not a production approval UI or a concurrent-writer guarantee.
