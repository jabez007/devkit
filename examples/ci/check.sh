#!/usr/bin/env bash
# Run the combined profile using an already installed, authorized devkit CLI.
set -euo pipefail
umask 077
: "${DEVKIT_BIN:?Set the absolute path to the installed devkit CLI}"
: "${DEVKIT_PROJECT:?Set the absolute path to the project}"
: "${DEVKIT_REPORTS:?Set a fresh report-directory path outside the project}"
: "${XDG_CONFIG_HOME:?Set the external operator configuration directory}"
mkdir "$DEVKIT_REPORTS"
export XDG_STATE_HOME="$DEVKIT_REPORTS/state"
cli=("$DEVKIT_BIN" --project "$DEVKIT_PROJECT" --json)

# Doctor reports activation problems. A successful doctor has not run project checks.
"${cli[@]}" doctor > "$DEVKIT_REPORTS/doctor.json" || exit "$?"
check_status=0
"${cli[@]}" check verify > "$DEVKIT_REPORTS/check.json" || check_status=$?
printf '%s\n' "$check_status" > "$DEVKIT_REPORTS/check-exit-code.txt"
cat "$DEVKIT_REPORTS/check.json"

# Evidence commands must not replace a failing check's exit code with success.
maintenance_failure="$check_status"
if [[ "$maintenance_failure" == 0 ]]; then maintenance_failure=3; fi
run_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("run_id", ""))' \
    "$DEVKIT_REPORTS/check.json") || exit "$maintenance_failure"
printf '%s\n' "$run_id" > "$DEVKIT_REPORTS/run-id.txt"
if [[ -n "$run_id" ]]; then
    "${cli[@]}" runs pin "$run_id" --reference ci:artifact \
        > "$DEVKIT_REPORTS/pin.json" || exit "$maintenance_failure"
    "${cli[@]}" runs show "$run_id" \
        > "$DEVKIT_REPORTS/shown.json" || exit "$maintenance_failure"
fi
"${cli[@]}" runs list > "$DEVKIT_REPORTS/runs.json" || exit "$maintenance_failure"
"${cli[@]}" runs prune > "$DEVKIT_REPORTS/prune-preview.json" || exit "$maintenance_failure"
exit "$check_status"
