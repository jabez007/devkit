---
status: accepted
---

# Keep delivery orchestration in Gas City and stack behavior in Devkit packs

[Issue #3](https://github.com/jabez007/devkit/issues/3) decides how to deliver
[the loop in #2](https://github.com/jabez007/devkit/issues/2) without duplicating
an orchestrator. The split keeps scheduling, sessions and task state in
Gas City and Beads. Devkit supplies domain checks and stack packs. This preserves
N1, N2, D1, D2 and section 10.2 of the
[architecture](../Composable_Developer_Toolkit_Architecture.md).

On November 3, 2026, all six qualification checks passed for the local
profile below, and the decision was accepted. A
missing prerequisite is an unrun check, not evidence that Gas City cannot
support the loop. The implementation plan and issue descriptions must follow
this split before production loop code lands.

## Runtime

Claude Code runs the implementation sessions through `claude -p`. Python code
makes no model calls. Gas City's native provider configuration supplies the
command, prompt, session lifecycle and runtime. The spike must verify a one-shot
launch explicitly: Gas City's default interactive Claude provider does not
establish this requirement. Native provider overrides are preferred to a new
Devkit session abstraction.

Claude subscription authentication is supported. An inherited
`ANTHROPIC_API_KEY` selects a separate billing path and must be excluded when
using the subscription. `claude --bare` forces API-key authentication and skips
hooks, so it cannot qualify subscription access or the unattended guard.
Credentials stay outside packs, transcripts, result payloads and commits.

## Core and stack packs

| Responsibility | Owner and interface |
|---|---|
| Discover, authorize and invoke checks | Existing Devkit foundation and plugin contract 1.0 |
| Domain validation and test results | Python specialization packages, usable without an orchestrator |
| Order steps, gate readiness and retry work | Gas City v2 formulas and native control dispatcher |
| Launch sessions, allocate worktrees and stop processes | Gas City runtime and session provider |
| Store tasks, dependencies, approval gates and workflow state | Beads through Gas City's native commands |
| Stack-specific prompts, checks and example briefs | A separate Gas City pack per stack |
| Base unattended rules | Shared hook assets installed by each stack pack, implemented in #5 |
| Stack-specific additional rules | The stack pack, without weakening the base rules |
| Saved verification results | Existing Devkit result envelopes and `RunStore` |

A Gas City pack is not a Python specialization. Native pack fields already
provide agents, formulas, skills, overlays, commands and runtimes. Keep plugin
contract 1.0 until two concrete Python callers demonstrate a missing interface.
An Odoo pack establishes the first workflow. The Vue pack in #12 tests which
choices can be shared. Record any core change it requires in this ADR.

Vue requires these shared-base changes:

- Move Git identity checks, protected publication inputs, bounded JSON reads
  and process capture into `base/assets/delivery_common.py`.
- Move exact-body draft creation and updates into `base/assets/delivery_pr.py`.
- Move native job binding, approved check dispatch, round feedback and publication
  into `base/assets/delivery_state.py`. Each stack supplies one adapter with
  `validate(job)` and `run(job, approved_brief)`. Stack entrypoints retain their
  existing native command names and metadata keys.

These moves preserve the first stack's CLI and check behavior. Each adapter
owns its complete job schema and tool-result interpretation. The shared module
does not select stack tools or grant effects. No Devkit foundation package or
plugin contract change is required. The check contracts and native first-stack
approval, red retry and installed-runtime case verify the extraction before
the Vue adapter is added.
An automated source check rejects first-stack names in the shared base and
Devkit foundation source.

## Job state and evidence

Do not add the SQLite job store proposed in #4. Gas City owns session and retry
state, and Beads owns tasks and the workflow graph. Devkit's
`Context.state_root` and `RunStore` continue to hold verification evidence, not a
second job lifecycle. Use native task IDs and retain command results as artifacts
linked from the task or draft pull request.

The current Devkit Beads adapter supports embedded Dolt workspaces and
sequential writers only. Gas City's standard setup uses a Dolt server. Sharing
the Beads 1.3.2 version does not make those modes compatible. The initial pack
uses native `gc` and `bd` commands for task state. It does not pass a server
workspace through the embedded-only adapter, patch Dolt tables, or create a
second ledger. Server-mode adapter support requires its own scoped acceptance
work before any Devkit evidence-association command is advertised for this loop.

## Check authorization

Use the existing `devkit-odoo --json` command for the read-only static gate.
Its exit status gates progress, and its JSON output is retained as an artifact.
This command shares the validator implementation but does not write a Devkit
run record. Use the authorized `devkit run` interface when saved evidence is
required.

Commands with wider effects retain operator policy. The operator prepares
explicit plugin trust and project grants before an unattended run, including
any per-task worktree paths. Repository configuration, the brief and the agent
cannot grant themselves access. A container is isolation, not an operator grant.
The production runtime check in #9 must declare and test its effects. This ADR
does not remove authorization from all checks or introduce a dispatcher that
silently issues grants.

## Existing packages

Keep operator policy, trust diagnostics, the optional MCP server and the
specialization template. They have independent callers: authorized command
invocation, operator diagnosis, native MCP clients and third-party plugin
authors. The loop does not need to consume every public interface to justify
its existence. #13 evaluates removals after the first real stack workflow;
absence from the loop alone is insufficient evidence for deletion.

## Code reuse

Crpaxton4/devcontainer-features remains a design reference. Reimplement any
Devkit-owned behavior from its requirements rather than copying its code,
matching architectural decision D7. Consume Gas City's native pack and runtime
interfaces directly. Invoke an upstream runtime script from the pinned Gas City
installation rather than vendoring or modifying it for this spike.

## Intake and brief approval

The loop consumes beads. An external tracker connector maps Odoo Project or
GitHub tasks into Beads independently of the development stack, following G5
and D4. Until a connector is implemented, an explicitly selected local bead is
enough to qualify the loop. A stack pack never grows its own tracker client.

A human approves the brief before implementation becomes ready. The formula
uses a native human gate. The brief, approval and task identity must remain
associated when the task resumes. A test fixture may close the gate on behalf
of its synthetic human, but that does not qualify a production approval UI.

## Qualification

Pin Gas City to `76843b86452109d9e7d150958cf220da81b9d01d` and Beads to 1.3.2.
Use a disposable Odoo repository and a minimal local pack. Record each check as
passed, failed or not run, with the actual command and a concise observation.
Never substitute formula compilation or a scripted agent for live qualification.

1. A real `claude -p` session runs in a per-task Git worktree inside an image
   built from the project's devcontainer configuration. Record which container
   lifecycle and configuration fields were exercised.
2. A native `[steps.check]` with `[steps.check.check] mode = "exec"` runs the
   validator against broken install order. The draft-PR step stays blocked.
   Fixing the addon lets the check pass and makes that step ready. Exercise the
   native dispatcher, not a Python imitation of its dependency rules.
3. The implement step is not ready while the human approval gate is open,
   and becomes ready only after explicit approval.
4. The live session can use a skill from the pack and the project's MCP server.
5. A `PreToolUse` guard installed beside Gas City's hooks refuses a force-push
   inside that session. This probes hook composition, not all #5 guard rules.
6. Task-state operations use one native Beads workspace. Report the Devkit
   adapter's server-mode rejection separately. A file-backed Gas City test
   store can qualify formula compilation and readiness, but cannot establish
   Beads server compatibility or concurrent-writer behavior.

Checks 1, 2, 3 and 5 are required before acceptance. A reproducible capability
failure in one of them requires reconsidering the runtime or the proposed split.
An environment or authentication failure leaves the decision proposed. Asset
and task-state integration gaps in checks 4 and 6 require a documented, exercised
workaround or a separate blocking follow-up. Do not silently count them as passes.
No production pull request, merge, force-push or remote branch deletion is
needed for the spike. A local draft-PR sentinel can test readiness; it does not
prove that GitHub created a draft pull request.

## Qualification results

The [repeatable driver](../../scripts/check_gascity_spike.py) and
[fixture instructions](../../examples/gascity-spike/README.md) exercise native
commands, not mocks. The final live run, with the driver at commit `09a38c0`,
used Gas City 1.4.3 at the pinned
revision, Beads 1.3.2, Dolt 2.6.0, devcontainer CLI 0.90.0, Docker 29.8.1 and
Claude Code 2.1.317 with subscription authentication.

| Check | Status | Observed result |
|---|---|---|
| Container and worktree | Passed | `gc worktree ensure` created the task branch and recorded provenance. `gc session new` launched a real one-shot Claude session through the upstream Docker runtime in the project's built image. |
| Native check and retry | Passed | Broken manifest order kept the draft-PR step blocked and created iteration 2. After the agent fixed only the manifest, `gc convoy control` passed the check and made the draft-PR step ready. |
| Human approval | Passed | The first implementation attempt was absent from `gc ready` before approval and present after the test driver explicitly closed the synthetic human gate and approval step. |
| Skill and project MCP | Passed | The transcript records `Skill` invoking `spike.probe` and a call to `mcp__spike__marker`. The driver also checks the MCP marker artifact. |
| Hook composition | Passed | Gas City's `SessionStart` and both `UserPromptSubmit` hooks returned exit code 0. The project guard returned a deny decision for exactly one `git push --force` request, alongside those hooks. The tool result for that call was an error carrying the guard's reason, `DEVKIT_SPIKE_FORCE_PUSH_DENIED`, so Claude Code blocked the push. An earlier run checked only the guard's marker file, which could not tell a blocked push from a failed one, because the fixture has no remote. |
| One task store | Passed | Native commands used one `proxied-server` Beads workspace. The Devkit adapter returned `blocked / UNSUPPORTED_BEADS_WORKSPACE`, confirming that the initial pack must use the native task-state workaround. |

The runtime profile needs explicit configuration:

- Build `gc` with upstream's release setting `CGO_ENABLED=0`. The driver verifies
  its exact source revision and clean-build metadata. The initial default host
  build linked ICU 70, which was absent from the Debian project image and made
  native hooks exit 127.
- Give the one-shot launcher its own readiness marker. The inherited
  interactive Claude prompt is not a readiness signal for `claude -p`.
- Pass `--agent spike.worker` to native worktree creation, and mount the
  reviewed pack directories read-only at the same paths inside the container.
  Otherwise the materialized skill symlinks do not resolve there.
- Load the generated Gas City settings alongside project settings and select
  the project's MCP file explicitly. The live assertions inspect actual tool
  calls and successful hook events, not just the agent's final summary.
- Mount only the selected subscription credential file read-only, and exclude
  API-key authentication. Isolate control, cache and state under the fixture
  root. Mount neither the user's home directory nor the Docker socket.

This qualifies one local Linux task with host networking, a Dockerfile image
build and an explicit container user. The static check runs on the host against
the shared task worktree. It does not qualify arbitrary devcontainer lifecycle
commands, live Odoo tests, a production GitHub draft-PR operation, resume across
answer rounds, or multiple hosts. The pinned Beads CLI also makes Gas City report
best-effort session leases; this serial spike does not establish concurrent-
writer guarantees. Those deployment and workflow checks remain with #5, #9,
#10 and #11. No second Devkit job store is needed to proceed with those issues.

The Odoo pack's live qualification exposed a further Beads 1.3.2 deployment
constraint. Native proxy discovery verifies a local process identity, so a
task container cannot adopt the host proxy's PID record. Host networking alone
does not solve that mismatch. The Odoo profile uses Beads' native external
connection configuration with a container-local proxy root and the host's
authoritative proxy as upstream. A read-only sidecar binding selects that
profile only in the container. This preserves one task database and native
commands without sharing host PIDs. See the [connection guide](../../integrations/gascity/odoo/README.md#connect-native-beads-from-the-container)
and the pinned native implementation links there. A host proxy restart requires
a refreshed connection profile. This is a qualified local deployment profile,
not a claim that arbitrary container or remote Beads layouts work.

## Backlog after acceptance

The Odoo pack completed its private-repository GitHub acceptance on 2026-11-04.
The native install-order failure prevented draft readiness. A real guarded
Claude session fixed and committed the task, and the installed version, static
and native Odoo checks passed. After explicit approval of the generated text,
`gc odoo delivery publish` created a real GitHub draft and verified its exact
body, title and checked commit. Retrying reused that draft without creating
a second PR. Native Beads recorded the PR URL and closed the draft step.
The [acceptance guide](../../integrations/gascity/odoo/README.md#prepare-the-private-github-acceptance-run)
describes the opt-in fixture and retained operator context.

The answer-loop qualification completed on 2026-11-05. A rejected synthetic
assumption produced a second behavior brief and a fresh native approval gate.
The live session reused the branch and worktree, changed the menu label and
committed it. Version, static and runtime checks passed, with two Odoo tests
and complete database cleanup. After approval of the revised exact text, the
native publisher updated the same private draft. A repeat returned the same
URL with one PR present. Native task metadata retained round 2 and the PR URL.
Eight transcript-derived tool failures imported into a separate synthetic
tooling bead once; repeating the import added no comments. The model's initial
friction report abbreviated output, so this qualifies native import and serial
deduplication, not unattended report completeness. No production approval UI
or concurrent-writer guarantee is claimed.

| Issue | Consequence |
|---|---|
| #2 | Update its ownership table and dependency order to this split. |
| #4, #6 | Superseded by native Gas City state and dispatch. |
| #5 | Keep the base guard hook and composition tests. |
| #7 | Replace proposed Python loop slots with native Gas City stack packs. |
| #8 | Implement brief prompts and a human approval gate in the pack. |
| #9 | Keep the independent Odoo runtime test command. |
| #10 | Deliver the Odoo pack against the qualified runtime and checks. |
| #11 | Use native task comments and round identity for answers and friction. |
| #12 | Deliver the Vue pack and record any proven core changes here. |
| #13 | Review packages against their independent callers and the working loop. |

These dispositions apply once this record merges. Do not advertise the loop
as implemented until the Odoo pack in #10 works. Each downstream issue links
the section of this record it implements.

## Sources

The source audit used the pinned Gas City revision above:

- [Formula v2 contract](https://github.com/gastownhall/gascity/blob/76843b86452109d9e7d150958cf220da81b9d01d/docs/reference/specs/formula-spec-v2.md): human gates, dependency readiness and native check controls.
- [Check expansion](https://github.com/gastownhall/gascity/blob/76843b86452109d9e7d150958cf220da81b9d01d/internal/formula/ralph.go): authored checks become control and iteration beads.
- [Agent configuration](https://github.com/gastownhall/gascity/blob/76843b86452109d9e7d150958cf220da81b9d01d/docs/guides/configuring-an-agent.md): native provider overrides and launch defaults.
- [Exec runtime protocol](https://github.com/gastownhall/gascity/blob/76843b86452109d9e7d150958cf220da81b9d01d/docs/reference/exec-session-provider.md): one-shot sessions, work directories, overlays and copied files.
- [Installation prerequisites](https://github.com/gastownhall/gascity/blob/76843b86452109d9e7d150958cf220da81b9d01d/docs/getting-started/installation.md): Dolt server requirements and tested Beads version.
- [Release builds](https://github.com/gastownhall/gascity/blob/76843b86452109d9e7d150958cf220da81b9d01d/.goreleaser.yml): static Go build configuration for portable runtime binaries.
- [Devkit Beads workspace validation](../../packages/devkit_beads/src/mccann_hub/devkit_beads/client.py): explicit embedded-mode and sequential-writer contract.
