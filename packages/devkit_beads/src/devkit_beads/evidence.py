"""Associate local evidence through the existing reference and retention store."""

from devkit.contracts import Context, DevkitError, JSONObject
from devkit.runs import RunStore

from devkit_beads.client import Beads, BeadsError


def associate(
    context: Context, client: Beads, workspace: JSONObject, args: JSONObject
) -> JSONObject:
    if context.state_root is None:
        raise BeadsError(
            "error", "EVIDENCE_UNAVAILABLE", "Invocation must supply the evidence store"
        )
    store = RunStore(context.state_root)
    try:
        existing = store.show(args["run_id"], context.project_root)
        if existing["state"] != "complete":
            raise BeadsError("blocked", "INCOMPLETE_RUN", "Only completed runs can be associated")
        item = client.show(args["ref"], workspace)
        if context.cancellation.is_set():
            raise BeadsError("cancelled", "CANCELLED", "Association cancelled before pinning")
        # reference revalidates the run under its lock; pruning between show and
        # reference fails explicitly rather than recreating a deleted record.
        reference = store.reference(args["run_id"], item["ref"], context.project_root)
    except DevkitError as exc:
        raise BeadsError("blocked", exc.reason, str(exc)) from exc
    except OSError as exc:
        raise BeadsError(
            "error", "REFERENCE_WRITE_FAILED", "Could not record evidence reference"
        ) from exc
    return {
        **reference,
        "workspace": workspace,
        "ref": item["ref"],
        "verification_status": existing["run"]["result"]["status"],
        "association": "Local evidence reference; Beads work item was not modified",
    }
