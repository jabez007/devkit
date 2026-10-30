"""A separately packaged command and check; registration has no side effects."""

from devkit.contracts import (
    CheckSpec,
    CommandResult,
    CommandSpec,
    Context,
    JSONObject,
    Specialization,
)


def greet(context: Context, arguments: JSONObject) -> CommandResult:
    return CommandResult(
        "success", "Greeting prepared", {"greeting": f"Hello, {arguments['name']}"}
    )


def register() -> Specialization:
    command = CommandSpec(
        "example.greet",
        "Produce a greeting without external side effects",
        greet,
        input_schema={
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 100}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["greeting"],
            "properties": {"greeting": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    return Specialization(
        "example", (command,), checks=(CheckSpec("example.greeting", command.id, {"name": "Dev"}),)
    )
