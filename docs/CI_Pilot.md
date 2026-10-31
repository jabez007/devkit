# Run Devkit checks in development CI

The [combined example](../examples/ci/project/devkit.toml) runs real Go tests and
validates a synthetic custom Odoo addon offline. It demonstrates profile results,
wheel-artifact trust and evidence retrieval. It is not a production Odoo module
or a validation of a client repository. Package versions remain foundation 0.1.1,
Go 0.1.0 and Odoo 0.5.0.

## Run the pilot locally

Use Linux, Bash, Python 3.12, uv and a Go toolchain. Run these commands from the
Devkit checkout. Build only the packages used by the example:

```sh
pilot_root=$(mktemp -d /tmp/devkit-ci.XXXXXXXX)
uv build --package devkit --out-dir "$pilot_root/wheels"
uv build --package devkit-go --out-dir "$pilot_root/wheels"
uv build --package devkit-odoo --out-dir "$pilot_root/wheels"
uv export --all-packages --no-dev --no-emit-workspace --no-hashes --frozen \
  --output-file "$pilot_root/constraints.txt"
uv venv --python 3.12 "$pilot_root/venv"
uv pip install --python "$pilot_root/venv/bin/python" \
  --constraint "$pilot_root/constraints.txt" "$pilot_root"/wheels/*.whl
export DEVKIT_BIN="$pilot_root/venv/bin/devkit"
export DEVKIT_PROJECT="$PWD/examples/ci/project"
export DEVKIT_REPORTS="$pilot_root/reports"
export XDG_CONFIG_HOME="$pilot_root/config"
python3 examples/ci/prepare_policy.py "$DEVKIT_PROJECT" "$pilot_root/wheels"
GOPROXY=off bash examples/ci/check.sh
```

`prepare_policy.py` creates a fresh external configuration and refuses to overwrite an
existing one. It approves exact Go/Odoo wheel versions and hashes for the selected
project and CLI surface. Keep the wheel files available while running checks.
The hash ties imported code to the selected wheel; it does not independently
verify the source or build process. For another project, review and approve its
package source and command effects before generating policy. Repository settings
cannot grant permissions.

The recipe requires a fresh report-directory path. It sets its evidence state to
that directory's `state` subdirectory. A successful `doctor` confirms activation
and declared prerequisites; it has not run Go tests or inspected the addon.
`check verify` performs those checks. All required checks must succeed.

The example's missing standard `base` addon remains **unknown** under its declared
incomplete inventory. Ordinary validation succeeds while reporting that gap. To
require certainty, configure dependency sources and set `strict_dependencies=true`.
With the shipped inventory, strict validation blocks. Do not set `complete=true`
just to change the result; it is a claim about the available source inventory.

## Run the GitHub Actions pilot

The [CI pilot workflow](../.github/workflows/ci-pilot.yml) runs on pushes and pull
requests. It builds the selected wheels, constrains installed dependencies using
`uv.lock`, and invokes the same recipe in a fresh environment. The synthetic
project stays inside the checkout so evidence records the source revision.
Operator configuration, wheels and reports live under the runner's temporary
directory. The job has a ten-minute timeout, read-only repository permissions and
no persisted checkout credentials. It does not publish packages or change branch
protection.

Open **Actions**, select **CI pilot**, then download the `devkit-pilot-…` artifact
from a completed run. The upload step runs after failed checks too. Reports expire
after seven days, subject to repository retention limits. A local Devkit pin does
not prevent GitHub from expiring an artifact.

To test failure reporting, manually dispatch one of the synthetic scenarios:

```sh
gh workflow run ci-pilot.yml --ref main -f scenario=go-failure
gh workflow run ci-pilot.yml --ref main -f scenario=odoo-blocked
gh workflow run ci-pilot.yml --ref main -f scenario=invalid-profile
```

These choices intentionally produce failed GitHub jobs with CLI exits 1, 2 and 3,
respectively. They change only the synthetic project in that disposable checkout;
its evidence correctly reports a dirty source tree. The default `passing` scenario
leaves those files unchanged. To download a report with the GitHub CLI:

```sh
gh run download <workflow-run-id> --dir /absolute/path/to/download
```

With one artifact, `gh run download` creates a subdirectory named after that
artifact. Set `XDG_STATE_HOME` to its `state` directory when retrieving evidence.
Use an isolated development runner without deployment secrets for project tests.
Devkit policy authorizes command effects; it does not isolate arbitrary Go code.
Review the workflow and operator policy as trusted CI code before adopting them
for another repository. Keep PR execution separate from privileged release jobs.

See GitHub's [artifact guide](https://docs.github.com/en/actions/tutorials/store-and-share-data)
and the pinned [upload action](https://github.com/actions/upload-artifact/tree/v7.0.2)
for retention and upload behavior. Forced job termination may prevent upload even
with `if: always()`.

## Interpret the result

The [recipe](../examples/ci/check.sh) preserves the check exit code after collecting
evidence. A successful check becomes exit 3 if an evidence-maintenance command
fails. An existing nonzero check exit is preserved. Doctor failures stop before
project checks and leave `doctor.json` for diagnosis. Setup or shell failures can
occur before a Devkit envelope exists.

| Exit | Meaning | Developer action |
| --- | --- | --- |
| 0 | Required checks succeeded. | Review remaining unverified coverage in the child results. |
| 1 | A check found a defect. | Read the failed child result and correct the code or declaration. |
| 2 | A check is blocked. | Supply authorization, prerequisites or required coverage. |
| 3 | Configuration, execution or evidence failed. | Inspect the reason and correct the setup. |
| 130 | The invocation was cancelled. | Rerun after resolving the interruption. |

Do not convert every nonzero result into a code defect or add `|| true` to make a
required check pass. Cancellation and forced runner termination can prevent final
report collection or upload.

## Retrieve evidence

The report directory contains doctor/profile JSON, the raw check exit code,
parent run ID, retrieved parent evidence, a run listing and a retention preview.
`state/devkit/runs` contains the persisted parent and child results. Child evidence
records include the approved plugin wheel digest. Operator policy, wheels and
source files are outside this directory.

Inspect the current run with the existing CLI:

```sh
export XDG_STATE_HOME="$DEVKIT_REPORTS/state"
run_id=$(cat "$DEVKIT_REPORTS/run-id.txt")
"$DEVKIT_BIN" --project "$DEVKIT_PROJECT" --json runs show "$run_id"
"$DEVKIT_BIN" --project "$DEVKIT_PROJECT" --json runs list
```

After downloading or moving reports, point at the new state directory and use
`--all-projects`. Evidence retains the original absolute project path, so the
normal project filter may otherwise exclude it:

```sh
export XDG_STATE_HOME="/absolute/path/to/download/state"
devkit --json runs list --all-projects
devkit --json runs show <run-uuid> --all-projects
```

These maintenance commands do not load project plugins or require the old
operator policy. They work with the foundation alone. Retrieved envelopes retain
historical evidence paths; use the run store instead of following those old paths.
Review report contents before enabling uploads for a real project. Go output can
contain project data; redaction does not make arbitrary test output public.

## Retain and prune local evidence

The recipe pins the profile parent with `ci:artifact`; its linked children remain
protected too. Local retention defaults to 30 days and the latest 100 completed
runs per project. Both limits must permit deletion, and a pin protects the family
regardless of age. The recipe previews pruning without deleting evidence.

For a persistent store, release a pin only when its evidence is no longer needed.
Preview the resulting plan before applying it:

```sh
devkit --project /absolute/project runs unpin <run-uuid> --reference ci:artifact
devkit --project /absolute/project runs prune
devkit --project /absolute/project runs prune --apply
```

For a downloaded store whose original project path is unavailable, add
`--all-projects` to each maintenance operation. Do not apply that flag to a shared
store unless the broader scope is intended. Local pins do not extend a CI
provider's artifact retention. Hosted runners discard local state after the job;
the uploaded artifact has a separate expiration date.
