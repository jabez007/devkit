import pytest
from devkit.app import create_service


@pytest.mark.parametrize(
    "body,status",
    [('t.Log("ok")', "success"), ('t.Fatal("failed")', "failed"), ('t.Skip("skipped")', "blocked")],
)
def test_real_go_tests(go_project, body, status):
    (go_project / "main_test.go").write_text(
        f'package check\nimport "testing"\nfunc TestExample(t *testing.T) {{ {body} }}\n'
    )
    result = create_service(go_project).execute("go.test")
    assert result["result"]["status"] == status, result
    assert result["producer"]["distribution"] == "devkit-go"
    assert result["result"]["data"]["tool_version"].startswith("go version")


def test_no_tests_and_missing_go(go_project, monkeypatch):
    assert create_service(go_project).execute("go.test")["result"]["reason"] == "NO_TESTS"
    monkeypatch.setenv("PATH", "/missing")
    assert create_service(go_project).execute("go.test")["result"]["reason"] == "MISSING_TOOL"
