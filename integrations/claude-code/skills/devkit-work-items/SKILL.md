---
name: devkit-work-items
description: Inspect optional Devkit Beads work items and explicitly link verification evidence. Use for a selected Beads development task or an intentional create, claim, update, comment, or close action through Devkit.
---

# Work with Beads through Devkit

Read `${CLAUDE_PLUGIN_ROOT}/references/work-items.md` and the checkout/discovery
procedure in `${CLAUDE_PLUGIN_ROOT}/references/verification.md` before use.
Resolve the active checkout again if the project changed. Beads owns task state;
Devkit records verification evidence. Native `bd` remains available to developers.

Inspect the workspace, ready items, selected item's description and dependencies.
Use the provider-qualified reference returned by Beads commands. Never select and
claim the next ready item automatically. Ask for a specific selection if ambiguous.
If the optional adapter or tooling is absent, explain the prerequisite and continue
independent verification when possible.

Creating, claiming, updating, commenting, closing, and associating evidence each
require an intentional workflow action within the user's authorization. Use the
required operator-chosen actor audit label for lifecycle mutations. Before posting
a comment, obtain approval of its text unless the user already supplied that text.
Existing command grants permit execution; they do not establish user intent.
Do not change policy, initialize a ledger, or fall back to native writes to bypass
a Devkit denial. Do not run concurrent Beads writers.

After a timeout, cancellation, malformed write response, evidence-write failure,
or `BEADS_WRITE_UNCERTAIN`, do not replay the mutation automatically. Inspect the
actual item and, when needed, native comment history. Report unresolved outcomes.
Association is separately idempotent: inspect run references before retrying the
same run/item pair. Never replay a whole workflow to repair one association.

Review verification results before explicitly associating a run. Preserve failed
and blocked evidence as such. Association protects evidence without posting an
external comment or changing task status. Summarize implementation, evidence,
remaining uncertainty, and the observed work-item state. Passing checks do not
authorize closure, establish human review, or prove deployment.
