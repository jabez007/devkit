# Gas City stack packs

Devkit stack packs use Gas City's native schema-2 imports, provider presets,
agents, formulas, skills and overlays. They use native `gc` and `bd` commands
for task state. Python specializations keep plugin contract 1.0 and remain
independently usable. See [ADR 0001](../../docs/adr/0001-delivery-loop-runs-on-gas-city.md).

The [Odoo delivery guide](odoo/README.md) covers the selected-bead workflow,
per-worktree check grants, devcontainer tools and reviewed draft publication.

## Pack layout

A stack pack has `pack.toml`, `agents/implementer/agent.toml`,
`agents/implementer/prompt.template.md`, `formulas/`, and stack-specific skills
or assets. Native imports compose the shared base:

```toml
[pack]
name = "example-stack"
schema = 2

[imports.base]
source = "/absolute/reviewed/devkit/integrations/gascity/base"
```

Use a local reviewed checkout, or pin remote imports to a reviewed commit with
Gas City's `source` and `version` fields. The base defines `devkit-claude`, a
native provider based on `builtin:claude` so Gas City retains Claude's skill
and hook family. It replaces the launch arguments and option schema with the
shared launcher. It starts through `/bin/sh` and Python. The launcher
announces `DEVKIT_SESSION_READY`, then runs `claude --print` once.

The stack's agent selects `provider = "devkit-claude"`,
`lifecycle = "one_shot"`, and `install_agent_hooks = ["claude"]`. The stack owns
its prompt, work directory and concurrency limit. Native `gc worktree ensure`
must receive `--agent <qualified-agent-name>` so Gas City installs the stack's
skills. Imported agents use the consuming import's namespace. The spike's
agent is `spike.worker`.

The base owns the launcher, readiness marker, subscription-auth variable
exclusion, explicit native settings, and explicit project MCP selection.
Prompts, formulas, check commands, brief examples and permitted tools belong to
the stack. Devkit plugin trust and per-worktree effect grants belong to the
operator. A native pack or container does not issue those grants.

## Session configuration

Set `DEVKIT_PACK_BASE` to the shared base's absolute path and
`DEVKIT_SESSION_CONFIG` to an operator-prepared JSON file:

```json
{
  "project": "/city/worktrees/task",
  "city_settings": "/city/.gc/settings.json",
  "mcp_config": "/city/worktrees/task/.mcp.json",
  "prompt_file": "/city/task-prompt.md",
  "allowed_tools": ["Read", "Edit", "Bash(devkit-odoo *)"],
  "artifacts": "/city/session-artifacts/task-attempt-1",
  "assigned_bead": "attempt-bead-id"
}
```

All paths are absolute. The native settings must contain Gas City's
`SessionStart` and `UserPromptSubmit` hooks. The launcher loads those settings
beside project settings, uses strict MCP configuration, and keeps permission
prompts disabled. `allowed_tools` is an explicit tool permission list. It does
not override the unattended guard or Devkit command policy. The JSON format
accepts no extra Claude flags. API-key and auth-token environment variables are
removed before the client starts; `--bare` is never used.
The optional `assigned_bead` names the one bead this attempt may close. The
launcher exports it as `GC_BEAD_ID`, which the guard reads. Without it or a
native `GC_BEAD_ID`, the guard refuses every close.
Inherited `GIT_*` variables are removed so they cannot redirect commands into
another checkout.

The artifact directory must be new for each attempt. It holds `agent.jsonl`,
`agent.stderr`, and `agent.exit`. The launcher preserves the client exit code.
Session configuration and prompts are each limited to 1 MB. Artifacts can
contain task content and remain operator-owned local evidence.

Sessions can write the repository's Git config, and the controller later runs
Git in that repository with the operator's credentials. Before each controller
Git command, the base reads local and per-worktree config and returns
`UNSAFE_GIT_CONFIG` for any key that is not on a short list of keys that cannot
start a program or change where Git acts. Find the key with
`git config --list --show-scope`. Every URL on the publishing remote must match
the selected GitHub repository.

## Prepare guard and runtime settings

Install the [guard's pinned parser](../unattended/README.md#install-and-enable)
in both the preparation interpreter and the project's container image. Build
the image using the project's devcontainer configuration. Select the upstream
`gc-session-docker` script from the pinned Gas City installation. The base
invokes that script and does not copy or replace its runtime implementation.

Create a deployment JSON file alongside the session configuration:

```json
{
  "session": "/city/session.json",
  "claude": "/absolute/installed/claude",
  "credentials": "/absolute/operator/.claude/.credentials.json",
  "config_dir": "/home/worker/.claude",
  "runtime": "/absolute/pinned/gascity/scripts/gc-session-docker",
  "image": "project-image:reviewed",
  "user": "1000:1000",
  "network": "host",
  "packs": ["/absolute/reviewed/stack-pack", "/absolute/pinned/gascity/internal/bootstrap/packs/core"],
  "readonly": ["/absolute/installed/gc", "/absolute/installed/bd"],
  "writable": ["/city/control", "/city/cache", "/city/state"],
  "default_branch": "main",
  "protected_branches": ["release/*"]
}
```

Supply every resolved pack directory, including transitive imports. The base
and shared guard directories are included automatically. Supply any required
native tools and read-only profiles in `readonly`; writable runtime directories
must already exist. Mounts retain their original absolute paths so native skill
symlinks resolve. All paths must be absolute and contain neither whitespace nor
commas, as the pinned native runtime splits its extra flags on spaces.
`config_dir` is a container path; all other configured paths are host paths.

Run preparation with the reviewed file:

```sh
python /absolute/devkit/integrations/gascity/base/assets/prepare.py /city/deployment.json
```

The helper validates all inputs, then atomically writes
`.claude/devkit-unattended-rules.json` and updates `.claude/settings.json` in the
selected project. It preserves existing project hooks and settings. Repeating
preparation does not duplicate its hook. Keep these operator-generated files
and session configuration out of commits.

`default_branch` and `protected_branches` come from the operator's review of
the target repository. They are required inputs, even when no additional
protected branches exist. Preparation never infers trusted protection settings
from writable local Git metadata. It preserves every base rule, adds the
reviewed default and protected branches, and rejects rules over 64 KiB. An
optional `stack_rules` path supplies a complete additive rule file accepted by
the actual shared guard. It cannot remove or weaken a base rule.

The JSON result has `session_provider`, for the control process's `GC_SESSION`,
and `workspace_env`, for the city's native `[workspace.env]`. Review and apply
those bindings before creating the session. Preparation does not start Docker,
Claude or a Gas City service. It does not change plugin trust or issue grants.

The generated runtime settings disable home mounting. They mount only the
selected subscription credential file at `config_dir/.credentials.json`,
read-only. Pack assets, guard code, project Claude settings, MCP configuration,
native Gas City settings, the session JSON, and prompt are read-only too.
Home-directory ancestors and socket paths are refused as additional mounts.
The native runtime still owns its ordinary city and worktree bindings.

The [spike](../../examples/gascity-spike/README.md) exercises this base with
real Gas City and Beads. Its deterministic stage uses synthetic credential and
client mount fixtures and calls no model or container. The opt-in live stage
tests a real Claude session, skill, project MCP and guard composition. Host
networking is the qualified local profile because native hooks reach the
fixture's local Dolt server. Other networking and devcontainer lifecycle
features require their own qualification.

This pack is covered by the repository's [GPL license](../../LICENSE).

## Lint a behavior brief

From the selected city directory, the base import supplies
`gc base brief lint /absolute/brief.json --task <selected-bead>`.
The command reads a UTF-8 JSON artifact with `schema_version = 1`, `task_id`,
`problem`, `acceptance_criteria`, `approach`, and `scope`. Scope has `in_scope`
and `out_of_scope` lists. `open_questions` is an optional list. See the
[Odoo example](odoo/examples/briefs/partial-delivery.json) and
[rewrite examples](odoo/examples/briefs/README.md).

The command refuses artifacts larger than 100,000 bytes and reports a task
identity mismatch. It flags obvious source paths, filenames, mixed-case dotted
names, call syntax, private or underscored identifiers, command flags and
backticks. Paths include single-component POSIX, home-relative and Windows drive
paths. Filename checks include documentation and configuration extensions,
case-insensitive source extensions, `.env` variants, `.gitignore`,
`.dockerignore`, `Dockerfile` and `Makefile`.

Findings identify sections and line numbers without echoing brief text. It
reports at most 100 findings. A clean result includes the exact artifact's
SHA-256.

These do not produce findings on their own: prose parentheses, decimal
quantities, `(s)` plurals, single-letter abbreviations such as `e.g.` and `U.S.`,
`Node.js`, `Vue.js`, and slash pairs of two plain parts such as `and/or` and
`24/7`. A relative path is flagged only when it has three or more parts or a
part containing `.`, `_` or `*`, so a two-part path like `models/order` is left
to the reviewer.

Recording and approval verification apply these same checks to retained briefs.
A newly detected prescription blocks reuse until a revised brief is recorded
in a new workflow.

Lint is a backstop. It cannot establish that prose states the right behavior or
contains no implementation prescription. A person reviews the full brief.
Passing lint does not close an approval gate or authorize implementation.

## Record and approve a brief

The base supplies the native `devkit-approved-brief` formula. It creates brief,
approval and implementation steps, with a native human gate on approval.
Cook it for an explicitly selected task and an absolute artifact path:

```sh
gc formula cook devkit-approved-brief --attach <task> \
  --var task=<task> --var brief_file=/absolute/task-worktree/brief.json --json
```

Keep the returned workflow root and step mapping. The brief step writes the
artifact and records it before closing:

```sh
gc base brief record /absolute/task-worktree/brief.json --task <task> --workflow <root>
```

Recording runs the lint, confirms the input bead exists, and verifies that the
workflow has the matching approval step and native human gate. It publishes an
exact copy under the native pack state directory, using the workflow identity
and content hash. It never overwrites an existing revision. Beads metadata links
that artifact, task, gate, approval step and SHA-256. There is no additional job
database or approval ledger.

After the brief step is complete, the operator reviews the full recorded text:

```sh
gc base brief show --workflow <root>
gc base brief approve --workflow <root> --sha256 <exact-reviewed-sha256>
```

Approval records the reviewed hash and task on the native gate, then closes the
gate and approval step through ordinary native commands. It does not force a
blocked close. If a close fails, the implementation remains blocked; resolve the
prerequisite and repeat the approval command. The command refuses any set
`DEVKIT_UNATTENDED` marker, including an empty value. Run it in the operator's
environment. The guard's `no-operator-state` rule refuses approval, and native writes to the
gate, in an unattended session. It inspects tool requests only, so code the
session runs, such as its own tests, can still reach native commands. Limit
what a deployment exposes accordingly. This CLI does not add a separate
identity service.

Implementation first verifies the saved approval:

```sh
gc base brief verify --workflow <root> --task <task>
gc base brief resume --task <task>
```

Verification requires the exact artifact hash, the selected task, matching native
workflow membership, and closed approval and gate beads carrying the reviewed
hash. Editing the original source file does not change the recorded artifact.
Editing the recorded copy fails hash verification. Recording another revision
on that workflow is refused; a revised brief needs a new workflow and approval.

Resume follows the recorded workflow reference in Beads rather than cooking
another workflow. Feedback tasks select their current round's explicit workflow.
For a legacy task with several workflows and no round pointer, it refuses to
choose; use `verify` with the intended root explicitly. An unapproved task does
not hold a global lock or stop another workflow from becoming ready.

The deterministic spike exercises two separate native workflows. It verifies
that implementation stays absent from `gc ready` before approval, explicit
approval releases only the selected workflow, and new command invocations retain
the exact task and brief association. Its approvals are synthetic test actions.
They do not establish that a person reviewed a production task or qualify an
external approval UI.

## Record questions, answers and tool friction

The operator starts the first feedback round before or after recording its brief:

```sh
gc base feedback begin --task TASK --workflow ROOT --branch devkit/TASK
```

An optional `--pr https://github.com/owner/repository/pull/NUMBER` records an
existing PR. The task holds its round number, workflow, branch and PR reference
in native metadata. Beginning again with the same selection is idempotent;
replacing an active branch or workflow is refused.

The agent records each question with its assumption and reason in a JSON array:

```json
[
  {
    "question": "What should the menu be called?",
    "assumption": "Use Delivery.",
    "reason": "That is the existing label."
  }
]
```

Import and inspect the records through native commands:

```sh
gc base feedback questions /absolute/questions.json --task TASK --workflow ROOT --round 1
gc base feedback show --task TASK --workflow ROOT --round 1
```

The result returns content-derived question IDs. The human either accepts an
assumption or supplies an answer, using the question's returned ID:

```json
[
  {"question_id": "QUESTION_SHA256", "accepted": false, "answer": "Call the menu Dispatch contacts."}
]
```

```sh
gc base feedback answers /absolute/answers.json --task TASK --workflow ROOT --round 1
```

An accepted assumption may omit `answer`. A rejection requires a nonempty
answer. Unknown question IDs, conflicting repeated answers and stale round
selections are refused. `begin` and `answers` require the operator's environment
with `DEVKIT_UNATTENDED` unset. The agent can record questions while unattended.

Friction records have exactly four fields. `observed` retains the quoted tool
output, including newlines or an empty output string:

```json
[
  {
    "command": "checker --verify",
    "expected": "A check result.",
    "observed": "checker: command not found\n",
    "action": "Used the installed executable's absolute path."
  }
]
```

Select a separate native bead for a nonempty friction report:

```sh
gc base feedback friction /absolute/friction.json --task TASK --workflow ROOT --round 1 \
  --friction-task TOOLING_BEAD
```

An empty array is the normal result and needs no friction bead. Nonempty reports
cannot use the task itself as the friction bead. Records use native task comments
under the author `Devkit feedback`, and marked comments from any other author
are ignored. Repeated sequential imports reuse content
IDs and add no comments; friction deduplicates its four fields within the
selected tooling bead. Use one importer per destination. Concurrent-import
deduplication is not qualified. Inputs are bounded to 100 records and 100 KB.
There is no additional feedback ledger or tracker client.

## Run a new round from rejected assumptions

After a round has an approved brief, completed implementation and a recorded PR,
the operator can derive the next brief from its answered questions. If the PR
was created after `begin`, associate its verified URL first:

```sh
gc base feedback link-pr --task TASK --workflow ROOT --round 1 \
  --pr https://github.com/owner/repository/pull/NUMBER
gc base feedback draft /absolute/round-two.json --task TASK --workflow ROOT --round 1
```

Every recorded question needs an answer. Accepted assumptions do not require a
new round. A rejection adds its answer to the proposed acceptance criteria.
Review the proposal and edit it before binding. If an answer contains
implementation instructions, author a behavior brief instead of using the
automatic draft. The new workflow records the answered-round digest so its
provenance stays associated with the reviewed revision.

Cook a fresh native workflow for the same selected task, using the stack's
formula and the proposal path. Then bind the next round:

```sh
gc base feedback next /absolute/round-two.json --task TASK --workflow ROOT --round 1 \
  --next-workflow NEW_ROOT
```

The command records the new brief, advances the task to round 2 and keeps the
same branch and PR. Its approval step and human gate must be fresh and open.
Complete the new brief step, then review and approve the exact new revision
with the existing brief commands. Until then, `gc base brief resume --task TASK`
returns `BRIEF_PENDING_APPROVAL`, even though round 1 was approved. A successful
round transition does not approve its brief or release implementation.

Repeating `next` with the same selection resumes that round without cooking
another workflow or replacing its artifact. A partial native metadata write can
be retried with the same root. `draft`, `next` and `link-pr` are operator commands
and refuse `DEVKIT_UNATTENDED`. A conflicting PR reference is refused.
