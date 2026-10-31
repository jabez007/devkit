"""Explicit lifecycle commands; Beads owns transitions, claims and closure rules."""

from collections.abc import Callable
from functools import partial

from devkit.contracts import EFFECTS, CommandResult, CommandSpec, JSONObject

from devkit_beads.client import Beads, BeadsError, invalid, items, local_id, project_id

ACTOR = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.@/-]{0,127}$"}
TEXT = {"type": "string", "maxLength": 16384, "pattern": r"^[^\u0000]*$"}
TITLE = {**TEXT, "minLength": 1, "maxLength": 256}
PRIORITY = {"type": "integer", "minimum": 0, "maximum": 4}
STATUS = {"enum": ["open", "in_progress", "blocked", "deferred"]}
UPDATE_FIELDS = ("title", "description", "priority", "status")
OPERATIONS = frozenset({"item.create", "item.claim", "item.update", "item.comment", "item.close"})


def commands(
    handler: Callable[..., CommandResult], reference: JSONObject
) -> tuple[CommandSpec, ...]:
    result = []
    for operation, description, properties, required in (
        (
            "create",
            "Create a Beads work item",
            {
                "title": TITLE,
                "description": TEXT,
                "priority": PRIORITY,
                "type": {
                    "enum": [
                        "task",
                        "bug",
                        "feature",
                        "epic",
                        "chore",
                        "decision",
                        "spike",
                        "story",
                        "milestone",
                    ]
                },
                "ref": reference,
            },
            ["title"],
        ),
        (
            "claim",
            "Atomically claim a Beads work item as the supplied actor",
            {"ref": reference},
            ["ref"],
        ),
        (
            "update",
            "Update ordinary fields with optional Beads concurrency guards",
            {
                "ref": reference,
                "title": TITLE,
                "description": TEXT,
                "priority": PRIORITY,
                "status": STATUS,
                "if_status": {**TEXT, "minLength": 1, "maxLength": 128},
                "if_assignee": {**TEXT, "maxLength": 128},
            },
            ["ref"],
        ),
        (
            "comment",
            "Add the supplied comment text to a Beads work item",
            {"ref": reference, "text": {**TEXT, "minLength": 1}},
            ["ref", "text"],
        ),
        (
            "close",
            "Close a Beads work item subject to Beads closure rules",
            {"ref": reference, "reason": {**TEXT, "minLength": 1}},
            ["ref", "reason"],
        ),
    ):
        schema: JSONObject = {
            "type": "object",
            "properties": {"actor": ACTOR, **properties},
            "required": ["actor", *required],
            "additionalProperties": False,
        }
        if operation == "update":
            schema["anyOf"] = [{"required": [field]} for field in UPDATE_FIELDS]
        result.append(
            CommandSpec(
                f"beads.item.{operation}",
                description,
                partial(handler, operation=f"item.{operation}"),
                input_schema=schema,
                effects=EFFECTS,
            )
        )
    return tuple(result)


def _arguments(operation: str, args: JSONObject, workspace: JSONObject) -> list[str]:
    if operation == "item.create":
        argv = [
            "create",
            f"--title={args['title']}",
            f"--description={args.get('description', '')}",
            f"--type={args.get('type', 'task')}",
            f"--priority={args.get('priority', 2)}",
        ]
        if "ref" in args:
            argv.append(f"--id={local_id(args['ref'], workspace)}")
        return argv
    identifier = local_id(args["ref"], workspace)
    if operation == "item.claim":
        return ["update", identifier, "--claim"]
    if operation == "item.close":
        return ["close", identifier, f"--reason={args['reason']}"]
    if operation == "item.comment":
        return ["comments", "add", identifier, "--", args["text"]]
    return [
        "update",
        identifier,
        *[
            f"--{key.replace('_', '-')}={args[key]}"
            for key in (*UPDATE_FIELDS, "if_status", "if_assignee")
            if key in args
        ],
    ]


def _comment(value: object, args: JSONObject, workspace: JSONObject) -> JSONObject:
    if not isinstance(value, dict):
        raise invalid()
    if (
        value.get("issue_id") != local_id(args["ref"], workspace)
        or value.get("text") != args["text"]
    ):
        raise invalid("Beads returned another comment")
    if not isinstance(value.get("author"), str) or not value["author"]:
        raise invalid()
    return {
        "ref": args["ref"],
        "comment": {
            "id": project_id(value.get("id")),
            "author": value["author"],
            "text": value["text"],
        },
    }


def mutate(client: Beads, workspace: JSONObject, args: JSONObject, operation: str) -> JSONObject:
    argv = _arguments(operation, args, workspace)
    value = client.write(args["actor"], *argv)
    try:
        if operation == "item.comment":
            data = _comment(value, args, workspace)
        else:
            rows = items([value] if operation == "item.create" else value, workspace["project_id"])
            if len(rows) != 1 or ("ref" in args and rows[0]["ref"] != args["ref"]):
                raise invalid("Beads did not return the requested work item")
            data = {"item": rows[0]}
    except BeadsError as exc:
        raise BeadsError(
            "error",
            "BEADS_WRITE_UNCERTAIN",
            "Beads returned an unexpected write response; inspect the item before retrying",
        ) from exc
    return {"workspace": workspace, "actor": args["actor"], **data}
