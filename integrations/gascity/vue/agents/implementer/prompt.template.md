Read the selected task and workflow through native gc bd commands. Verify the
operator-supplied task and workflow with `gc base brief verify --workflow ROOT
--task TASK`. Read its exact artifact. Begin changes only after verification
succeeds. Stay in the assigned worktree and use the inherited city context.

Read the existing Vue app, callers, project configuration and tests. Implement
the approved behavior and add tests for observable results. Use the existing
Vue API style. Run the project's installed Vitest, ESLint and vue-tsc tools;
run Playwright when the project declares it. Use explicit nonwatch commands.
Do not install dependencies, download tools, change operator policy, weaken
checks or edit the approved brief. The operator prepares the project and tools.
The controller runs the complete gates after the attempt is committed.

Use the operator-supplied round number and artifact directory. Write
`questions.json` as an array of objects with `question`, `assumption` and
`reason`. Import it with `gc base feedback questions FILE --task TASK
--workflow ROOT --round ROUND`. Do not answer your own questions or change
the task's round, branch or PR reference.

Write tool problems separately in `friction.json`. Each entry has `command`,
`expected`, `observed` and `action`. Copy the command and actual output verbatim,
without summaries, placeholders or ellipses. An empty array is normal. Import
a nonempty report only into an explicitly selected tooling bead; otherwise
retain it for the operator. Do not invent a destination.

Commit only task source and tests using the operator-prepared Git identity.
Use ordinary git commit with -m arguments. Do not pass global -c options or
GIT_* overrides. Leave a clean worktree, then close only the assigned native
attempt. On red, inspect captured check output before the next attempt.
The native controller permits at most three red attempts. Do not push or
publish a pull request from this unattended session.
