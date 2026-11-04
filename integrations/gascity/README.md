# Gas City stack packs

Devkit stack packs use Gas City's native schema-2 imports, provider presets,
agents, formulas, skills and overlays. They use native `gc` and `bd` commands
for task state. Python specializations keep plugin contract 1.0 and remain
independently usable. See [ADR 0001](../../docs/adr/0001-delivery-loop-runs-on-gas-city.md).

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
  "artifacts": "/city/session-artifacts/task-attempt-1"
}
```

All paths are absolute. The native settings must contain Gas City's
`SessionStart` and `UserPromptSubmit` hooks. The launcher loads those settings
beside project settings, uses strict MCP configuration, and keeps permission
prompts disabled. `allowed_tools` is an explicit tool permission list. It does
not override the unattended guard or Devkit command policy. The JSON format
accepts no extra Claude flags. API-key and auth-token environment variables are
removed before the client starts; `--bare` is never used.

The artifact directory must be new for each attempt. It holds `agent.jsonl`,
`agent.stderr`, and `agent.exit`. The launcher preserves the client exit code.
Session configuration and prompts are each limited to 1 MB. Artifacts can
contain task content and remain operator-owned local evidence.

The [spike](../../examples/gascity-spike/README.md) exercises this base with
real Gas City and Beads, with an opt-in live Claude container session. Its
current caller installs the shared guard in project settings and supplies
read-only pack, settings, prompt and credential mounts. These choices must
remain explicit when preparing another stack.

This pack is covered by the repository's [GPL license](../../LICENSE).
