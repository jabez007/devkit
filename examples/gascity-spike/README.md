# Qualify the delivery-loop split

This opt-in fixture exercises [ADR 0001](../../docs/adr/0001-delivery-loop-runs-on-gas-city.md).
It is not the production Odoo pack from issue #10. It runs against real Gas City,
Beads and Dolt commands. The optional live stage launches Claude through Gas
City's native Docker runtime and uses an existing Claude subscription.

The deterministic stage compiles and cooks a native formula, creates a Git
worktree through `gc worktree ensure`, and checks approval and retry behavior
through public commands. An intentionally broken addon fails the static gate,
and the downstream draft-PR step stays blocked. The live agent fixes the addon,
invokes a pack skill, calls the project MCP server, and receives a hook refusal
for `git push --force` and a Read request for a synthetic credential canary.
The native check then passes and releases the draft-PR step. No Git remote is
configured and no GitHub pull request is created. The deterministic stage also
sends representative requests to the actual shared unattended guard.

## Prepare the tools

Install this repository's locked development environment. Supply these tools
as absolute paths:

- A clean Gas City checkout at `76843b86452109d9e7d150958cf220da81b9d01d` and a
  `gc` binary built from that exact checkout. The driver checks Go build metadata.
  The source build requires Go 1.27.3. A Go command is also needed to inspect
  the binary's revision. Build with `CGO_ENABLED=0`, as upstream releases do.
  A default host build can link ICU libraries absent from the project image.
- Beads 1.3.2 and Dolt 2.6.0. The driver uses a synthetic Dolt author identity
  under its disposable `DOLT_ROOT_PATH`.
- devcontainer CLI 0.90.0 and a working local Linux Docker daemon for `--live`.
- Claude Code and its existing subscription credential file for `--live`.

Run from a shell with Docker access. An existing Docker-group member with stale
process groups can start a fresh shell with `sg docker`. This does not install
or reconfigure Docker.

## Run the spike

Choose a new, nonexistent output directory. Keep its artifacts outside this
repository. From the repository root, run:

```sh
uv run python scripts/check_gascity_spike.py \
  --root /tmp/devkit-delivery-spike \
  --gc /absolute/path/to/gc \
  --gascity-source /absolute/path/to/pinned/gascity \
  --bd /absolute/path/to/bd \
  --dolt /absolute/path/to/dolt \
  --devcontainer /absolute/path/to/devcontainer \
  --claude /absolute/path/to/claude \
  --credentials "$HOME/.claude/.credentials.json"
```

Add `--live` to run the real container session. Without it, no model is called.
The driver requires all tool paths for both modes, but only the live stage uses
Docker, devcontainer CLI and Claude credentials. Tool and mount paths must not
contain whitespace because the native Docker runtime splits its extra flags
on spaces.

The driver writes progress to stderr and a JSON summary to stdout. It retains
the fixture and transcripts under `--root`, closes its session and asks Beads
to stop its owned Dolt process. It never registers a supervisor service or
initializes a task ledger in the Devkit checkout.

## Tested runtime choices

The image is built from the fixture's Dockerfile and devcontainer configuration,
with locally built Devkit wheels constrained by `uv.lock`. Gas City's Docker
runtime launches that image as UID 1000 with host networking so its native
hooks can reach the fixture's local task store. This tests the image build and
container user. It does not qualify arbitrary devcontainer features, lifecycle
commands, mounts, other operating systems or multi-host scheduling.

The one-shot launcher publishes an explicit readiness marker. It loads Gas
City's generated `.gc/settings.json` alongside the project's guard settings,
and explicitly selects the project's MCP file. Native worktree creation uses
`--agent spike.worker` to materialize the pack's skills. The referenced pack
directories are mounted read-only at their original paths so those skill
symlinks resolve inside the container.

The shared [unattended guard](../../integrations/unattended/README.md), project
Claude settings and synthetic canary directory are mounted read-only too. The
image installs the guard's pinned parser. The driver checks the actual error
tool result, matching its tool-call ID and rule reason, for both denials. It
rejects a transcript containing the canary's synthetic contents. It never asks
the agent to read the real authentication file.

The runtime mounts the selected Claude subscription credential file read-only.
It does not mount the user's home directory or Docker socket. The driver
forwards a small environment allowlist and excludes API-key authentication.
Its temporary control, cache and state directories are shared with the runtime;
its synthetic Dolt identity profile is mounted read-only.
Do not copy credentials into fixture files, transcripts or commits.

The gate runs the read-only validator on the host against the shared worktree.
It does not execute Odoo or qualify the runtime test command in issue #9.
The live force-push and canary probes exercise composition of the shared guard
beside native hooks. The broader rule matrix is in `tests/test_unattended_guard.py`;
these two live probes alone do not qualify every rule or arbitrary program behavior.

The native task store uses Beads 1.3.2 in `proxied-server` mode. The driver also
checks that Devkit's embedded-only adapter refuses that workspace with
`UNSUPPORTED_BEADS_WORKSPACE`. Use native `gc` and `bd` commands for this loop's
task state. The spike does not establish server-mode adapter support or
concurrent-writer guarantees.
