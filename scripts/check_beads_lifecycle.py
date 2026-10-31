"""Exercise native Beads lifecycle rules through an independently installed adapter."""

import json
from pathlib import Path

from check_wheels import cli, run

EFFECTS = ["read_fs", "write_fs", "execute_process", "network_read", "network_write"]
ACTOR = "devkit-acceptance"


def invoke(root, project, env, operation, arguments, expected=0):
    return cli(
        root,
        project,
        env,
        "run",
        f"beads.item.{operation}",
        "--args",
        json.dumps({"actor": ACTOR, **arguments}),
        expected=expected,
    )


def grant(root, project):
    path = root / "config/devkit/policy.toml"
    with path.open("a") as stream:
        for operation in ("create", "claim", "update", "comment", "close"):
            stream.write(
                f'\n[commands."beads.item.{operation}"]\nproject={json.dumps(str(project))}\n'
            )
            stream.write(f'effects={json.dumps(EFFECTS)}\nsurfaces=["cli","python","mcp"]\n')


def python_claim(root, project, env, reference, expected):
    code = """
import json,sys
from pathlib import Path
from devkit.app import create_service
result = create_service(Path(sys.argv[1])).execute("beads.item.claim", {
    "ref":sys.argv[2], "actor":"devkit-acceptance"})
assert result["result"] == json.loads(sys.argv[3]), result
"""
    run(
        str(root / "venv/bin/python"),
        "-c",
        code,
        str(project),
        reference,
        json.dumps(expected),
        env=env,
        cwd=project,
    )


def comment_mcp(root, project, env, reference):
    code = """
import anyio,json,os,sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def check():
    params=StdioServerParameters(
        command=sys.argv[1], args=["--project",sys.argv[2]], env=dict(os.environ))
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            result = await session.call_tool("beads.item.comment", {
                "ref":sys.argv[3], "actor":"devkit-acceptance",
                "text":"Synthetic acceptance comment; verification remains a separate action"})
            envelope=result.structuredContent
            assert envelope["result"]["status"] == "success", envelope
            assert envelope["result"]["data"]["comment"]["author"] == "devkit-acceptance"
            stored=json.loads(Path(envelope["evidence_path"]).read_text())
            assert stored["result"] == envelope["result"]
anyio.run(check)
"""
    run(
        str(root / "venv/bin/python"),
        "-c",
        code,
        str(root / "venv/bin/devkit-mcp"),
        str(project),
        reference,
        env=env,
        cwd=project,
    )


def exercise(root, project, env, blocked_ref):
    denied = invoke(root, project, env, "create", {"title": "Must not be created"}, expected=2)
    assert denied["result"]["reason"] == "DENIED"
    grant(root, project)
    created = invoke(
        root, project, env, "create", {"title": "--force", "description": "Lifecycle acceptance"}
    )
    item = created["result"]["data"]["item"]
    assert item["title"] == "--force" and item["created_by"] == ACTOR
    reference = item["ref"]
    claimed = invoke(root, project, env, "claim", {"ref": reference})
    assert claimed["result"]["data"]["item"]["assignee"] == ACTOR
    python_claim(root, project, env, reference, claimed["result"])
    conflict = invoke(
        root, project, env, "claim", {"ref": reference, "actor": "other-actor"}, expected=3
    )
    assert conflict["result"]["reason"] == "BEADS_WRITE_UNCERTAIN"
    guarded = invoke(
        root,
        project,
        env,
        "update",
        {"ref": reference, "title": "No change", "if_status": "open"},
        expected=2,
    )
    assert guarded["result"]["reason"] == "BEADS_CONFLICT"
    updated = invoke(
        root,
        project,
        env,
        "update",
        {
            "ref": reference,
            "priority": 1,
            "description": "Verified update",
            "if_status": "in_progress",
            "if_assignee": ACTOR,
        },
    )
    assert updated["result"]["data"]["item"]["priority"] == 1
    assert updated["result"]["data"]["item"]["title"] == "--force"
    comment_mcp(root, project, env, reference)
    check = cli(root, project, env, "check", "verify")
    arguments = json.dumps({"ref": reference, "run_id": check["run_id"]})
    for _ in range(2):
        linked = cli(root, project, env, "run", "beads.evidence.associate", "--args", arguments)
        assert linked["result"]["data"]["references"] == [reference]
    # Beads, rather than Devkit, decides whether blockers permit closure.
    refused = invoke(
        root, project, env, "close", {"ref": blocked_ref, "reason": "Still blocked"}, expected=3
    )
    assert refused["result"]["reason"] == "BEADS_WRITE_UNCERTAIN"
    shown = cli(
        root, project, env, "run", "beads.item.show", "--args", json.dumps({"ref": blocked_ref})
    )
    assert shown["result"]["data"]["item"]["status"] == "open"
    closed = invoke(
        root, project, env, "close", {"ref": reference, "reason": "Verification reviewed"}
    )
    assert closed["result"]["data"]["item"]["status"] == "closed"
    assert (
        invoke(root, project, env, "close", {"ref": reference, "reason": "Verification reviewed"})[
            "result"
        ]
        == closed["result"]
    )
    retained = cli(root, project, env, "runs", "show", check["run_id"])["result"]["data"]
    assert retained["references"] == [reference]
    # Local association never secretly writes a comment; only the explicit command did.
    code = """
import json,os,subprocess,sys
result = subprocess.run(["bd","--readonly","--sandbox","--json","comments",sys.argv[1]],
    capture_output=True,text=True,check=True,env=dict(os.environ))
rows=json.loads(result.stdout)
assert len(rows)==1,rows
assert rows[0]["author"]=="devkit-acceptance"
"""
    run(str(root / "venv/bin/python"), "-c", code, reference.split(":")[-1], env=env, cwd=project)
    assert Path(check["evidence_path"]).exists()
    print(
        "PASS: writable Beads lifecycle, restricted policy, native conflicts, "
        "comments, evidence and closure"
    )
