"""Optional Beads commands. Registration performs no tool or workspace access."""

from functools import partial

from devkit.contracts import (
    CheckSpec,
    CommandResult,
    CommandSpec,
    Context,
    JSONObject,
    Specialization,
)

from devkit_beads.client import Beads, BeadsError, items, local_id
from devkit_beads.evidence import associate

# Reads do not change work-item data, but Beads embedded Dolt rewrites internal
# files with unchanged bytes. Declare that observed filesystem effect honestly.
READ_EFFECTS = frozenset({"read_fs", "write_fs", "execute_process", "network_read"})
REFERENCE = {"type": "string", "pattern": r"^beads:[0-9a-f-]{36}:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"}


def _operation(
    client: Beads, workspace: JSONObject, args: JSONObject, operation: str
) -> JSONObject:
    scope = workspace["project_id"]
    if operation == "evidence.associate":
        return associate(client.context, client, workspace, args)
    if operation == "workspace":
        return {"workspace": workspace}
    if operation == "item.show":
        return {"workspace": workspace, "item": client.show(args["ref"], workspace)}
    if operation == "ready":
        limit = args.get("limit", 20)
        rows = items(client.query("ready", "--limit", str(limit)), scope)
        return {
            "workspace": workspace,
            "items": rows,
            "limit": limit,
            "possibly_truncated": len(rows) == limit,
        }
    identifier = local_id(args["ref"], workspace)
    client.show(args["ref"], workspace)
    rows = items(client.query("dep", "list", identifier), scope, dependencies=True)
    return {
        "workspace": workspace,
        "ref": args["ref"],
        "dependencies": rows,
        "coverage": "Direct outgoing dependencies; readiness is determined by beads.ready",
    }


def execute(context: Context, args: JSONObject, *, operation: str) -> CommandResult:
    try:
        client = Beads(context)
        data = _operation(client, client.workspace(), args, operation)
        return CommandResult(
            "success",
            "Evidence reference recorded; work item unchanged"
            if operation == "evidence.associate"
            else "Beads inspection complete",
            data,
        )
    except BeadsError as exc:
        return CommandResult(exc.status, str(exc), reason=exc.reason)
    except OSError:
        return CommandResult("blocked", "Cannot access Beads workspace", reason="BEADS_UNAVAILABLE")


def register() -> Specialization:
    commands = []
    for operation, description, properties, required in (
        ("workspace", "Inspect a Beads 1.3.2 embedded workspace", {}, []),
        ("item.show", "Read a provider-qualified Beads work item", {"ref": REFERENCE}, ["ref"]),
        (
            "ready",
            "List ready work items using Beads readiness rules",
            {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            [],
        ),
        (
            "dependencies",
            "Inspect direct dependencies of a Beads work item",
            {"ref": REFERENCE},
            ["ref"],
        ),
    ):
        commands.append(
            CommandSpec(
                f"beads.{operation}",
                description,
                partial(execute, operation=operation),
                input_schema={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
                effects=READ_EFFECTS,
            )
        )
    commands.append(
        CommandSpec(
            "beads.evidence.associate",
            "Explicitly protect an existing run with a Beads issue reference",
            partial(execute, operation="evidence.associate"),
            input_schema={
                "type": "object",
                "properties": {
                    "ref": REFERENCE,
                    "run_id": {"type": "string", "pattern": r"^[0-9a-f-]{36}$"},
                },
                "required": ["ref", "run_id"],
                "additionalProperties": False,
            },
            effects=READ_EFFECTS,
        )
    )
    return Specialization(
        "beads",
        tuple(commands),
        environment_checks=(CheckSpec("beads.workspace", "beads.workspace"),),
    )
