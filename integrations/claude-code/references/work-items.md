# Optional Beads procedure

Use the verification reference to select the checkout and inspect authorization
first. This adapter supports Beads 1.3.2 embedded workspaces and sequential linked
worktrees sharing the native ledger. Each checkout still needs its own Devkit
project authorization and retains its own verification evidence. Server-backed
configurations and simultaneous writers are not qualified. Do not remove guards
or create another ledger to work around an unsupported workspace.

## Inspect a selected item

```sh
devkit --project /resolved/checkout --json run beads.workspace
devkit --project /resolved/checkout --json run beads.ready --args '{"limit":10}'
devkit --project /resolved/checkout --json run beads.item.show --args '{"ref":"beads:PROJECT_UUID:ISSUE_ID"}'
devkit --project /resolved/checkout --json run beads.dependencies --args '{"ref":"beads:PROJECT_UUID:ISSUE_ID"}'
```

Copy the qualified `ref` from returned items. If given only a native issue ID, use
the workspace's returned project ID to qualify it and verify it with `item.show`.
Read the description, status, assignee, dependencies, and readiness before proposing
work. Unavailable tools, malformed responses, and workspace errors are reported in
the existing envelope. Native Beads owns dependency and readiness decisions.

## Perform an intentional lifecycle action

Use only actions within the user's requested workflow. Replace the sample actor
with the operator's chosen audit label; it is not a credential or proof of identity.
Use JSON serialization for user-provided text instead of shell interpolation.

```sh
devkit --project /resolved/checkout --json run beads.item.create --args '{"actor":"claude-code/developer","title":"Selected development work","description":"Agreed scope","type":"task"}'
devkit --project /resolved/checkout --json run beads.item.claim --args '{"actor":"claude-code/developer","ref":"beads:PROJECT_UUID:ISSUE_ID"}'
devkit --project /resolved/checkout --json run beads.item.update --args '{"actor":"claude-code/developer","ref":"beads:PROJECT_UUID:ISSUE_ID","description":"Agreed revised scope","if_status":"in_progress"}'
devkit --project /resolved/checkout --json run beads.item.comment --args '{"actor":"claude-code/developer","ref":"beads:PROJECT_UUID:ISSUE_ID","text":"User-approved comment text"}'
devkit --project /resolved/checkout --json run beads.item.close --args '{"actor":"claude-code/developer","ref":"beads:PROJECT_UUID:ISSUE_ID","reason":"Explicitly accepted work"}'
```

These are alternatives, not an automatic sequence. Claim only the selected item.
Use update guards when relying on an observed status or assignee. A conflict needs
fresh inspection. A timeout, cancellation, malformed response, or failure to persist
evidence can follow a successful native write. Inspect `item.show` and, for uncertain
comments, native `bd comments ISSUE_ID --json` before deciding whether to retry.
If observation cannot establish what happened, report uncertainty and stop writes.
Do not silently retry creation, comments, or closure through another interface.

## Associate an existing verification run

Read `runs show RUN_UUID` for this checkout and inspect the selected item first.
On an explicit association request, use the returned run UUID and qualified item ref:

```sh
devkit --project /resolved/checkout --json run beads.evidence.associate --args '{"ref":"beads:PROJECT_UUID:ISSUE_ID","run_id":"RUN_UUID"}'
devkit --project /resolved/checkout --json runs list --reference 'beads:PROJECT_UUID:ISSUE_ID'
devkit --project /resolved/checkout --json runs show RUN_UUID
```

Association validates the live issue, then stores a local evidence reference. It
does not comment on the issue or change its status. Repeating the same association
does not duplicate references. References protect runs from pruning until explicitly
removed. An invalid issue or wrong-project run must be corrected rather than linked
under a guessed identity. After partial failure, inspect the run's references and
retry only that same association if needed. Failed and blocked runs remain failed
and blocked after association. Reference lookup and historical evidence still work
when Beads or the Claude plugin is removed.
