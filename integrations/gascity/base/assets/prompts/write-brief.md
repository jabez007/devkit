Read the explicitly selected bead {{task}} through native task commands. Write
its brief to {{brief_file}}. State the problem, acceptance criteria, approach as
observable behavior, and scope. Put uncertain business decisions in open questions.
Leave implementation choices for the specification after approval.

Use a UTF-8 JSON object with schema_version 1, task_id "{{task}}", problem text,
acceptance_criteria as a nonempty list, approach text, scope with in_scope and
out_of_scope lists, and open_questions as a list. Keep the artifact at most
100,000 bytes. Describe what a person can observe and how they can tell it is
right. Code identifiers, paths, commands and implementation mechanisms belong
outside the brief.

Find this workflow's root from the current bead's native gc.root_bead_id metadata.
Run gc base brief record with the artifact, --task {{task}}, and --workflow set
to that root. This command lints and binds the exact revision. The step is done
when recording succeeds and the operator can review the bound artifact. Leave
the approval gate for the operator.
