---
name: devkit-verification
description: Use Devkit to discover authorized development checks, verify a project, and explain persisted evidence and missing coverage. Use when the user requests Devkit verification or wants to inspect a Devkit run.
---

# Verify with Devkit

Read `${CLAUDE_PLUGIN_ROOT}/references/verification.md` before running commands.
Use the reviewed `devkit` executable already installed for this project. If it is
missing, explain setup and stop the Devkit operation. Do not install or authorize
anything automatically.

Resolve the active checkout with `${CLAUDE_PLUGIN_ROOT}/scripts/checkout.py`, or
pass the user's explicitly selected project directory to its `--project` option.
The plugin directory is only a source of instructions. Never use it as the project
root or substitute a linked worktree's main checkout. Repeat resolution after a
project change. Pass the resolved absolute path to every Devkit invocation.

Inspect installed, selected, and trusted plugins, then prerequisites and authorized
commands. Read configured profiles before choosing checks. Use the CLI even if MCP
is absent. Use MCP only after confirming its fixed project path matches this
checkout and its tools are authorized. Both routes use Devkit's existing contracts.

Run checks that match the request. Read structured results and child evidence,
including coverage and checks not performed. A successful doctor is not project
validation. A passing static check does not prove runtime behavior or approval.
Report defects separately from blocked or unknown coverage, with run IDs and
retrieval commands. Do not treat denied authorization as a defective project.

Work items are optional. Associate evidence only with an explicitly selected item
and an intentional association action, using the `devkit-work-items` skill. Do not
claim, comment on, or close tasks as a consequence of verification alone.
