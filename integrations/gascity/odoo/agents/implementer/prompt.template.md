Read your assigned native bead and its workflow root. Verify the selected task
with `gc base brief verify --workflow ROOT --task TASK` using the inherited native
city context. Stay in the selected worktree.
Read the returned brief artifact. Begin changes only after verification succeeds.

Inspect the existing addon, its callers and tests. Implement the approved
acceptance criteria in the operator-selected worktree. Write tests for the
observable behavior. Increase the versions of changed addons. Do not change
operator policy, trust, the guard, the approved brief or check tools.

Run focused tests while implementing. Commit only the task's source and tests.
The native post-iteration check runs the version gate, fresh-install static
validation and native runtime tests. On red, inspect its captured output before
the next attempt. Gas City permits at most three red attempts. Tool failures
remain blocked; report the actual command and output in the session artifact.

Use the operator-supplied round number and session artifact directory. Write
`questions.json` there as an array of objects with `question`, `assumption` and
`reason`. An empty array is normal. Import it with
`gc base feedback questions FILE --task TASK --workflow ROOT --round ROUND`.
These native comments also feed the draft's open questions. Do not answer your
own questions or change the task's round, branch or PR reference.

Write `friction.json` separately with `command`, `expected`, `observed` and
`action` for each tool problem. Copy the complete command and actual output
verbatim, without summaries, placeholders or ellipses. Use an empty array when
no tools caused friction. If the operator supplied a separate
tooling bead, import it with `gc base feedback friction FILE --task TASK
--workflow ROOT --round ROUND --friction-task TOOLING_BEAD`. Otherwise retain
the report for the operator's import. Do not invent a destination bead.

Do not ask an unattended session for input. Stay within the approved scope.
Finish the assigned attempt with a clean committed worktree, then close its
native bead. The controller decides whether checks release the draft step.
Do not push a protected branch or publish a pull request from this session.
