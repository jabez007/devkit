import pytest
from mccann_hub.devkit.app import create_service


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
    assert result["producer"]["distribution"] == "mccann-hub-devkit-go"
    assert result["result"]["data"]["tool_version"].startswith("go version")
    count = {"success": "passed", "failed": "failed", "blocked": "skipped"}[status]
    assert result["result"]["data"]["tests"][count] == 1


def test_no_tests_and_missing_go(go_project, monkeypatch):
    assert create_service(go_project).execute("go.test")["result"]["reason"] == "NO_TESTS"
    monkeypatch.setenv("PATH", "/missing")
    assert create_service(go_project).execute("go.test")["result"]["reason"] == "MISSING_TOOL"


def write_tests(
    project, *bodies, name="main_test.go", imports=("testing",), header="", prefix="Test"
):
    tests = "".join(
        f"func {prefix}{index}(t *testing.T) {{ {body} }}\n" for index, body in enumerate(bodies)
    )
    quoted = "; ".join(f'"{item}"' for item in imports)
    (project / name).write_text(f"{header}package check\nimport ({quoted})\n{tests}")


def test_large_passing_suites_are_counted(go_project):
    write_tests(go_project, *['t.Log("ok")'] * 600)
    result = create_service(go_project).execute("go.test")["result"]
    assert result["status"] == "success", result["summary"]
    assert result["data"]["tests"]["passed"] == 600


def test_tests_see_the_callers_environment(go_project, monkeypatch):
    monkeypatch.setenv("APP_TEST_DSN", "postgres://localhost/test")
    write_tests(
        go_project,
        'if os.Getenv("APP_TEST_DSN") == "" { t.Fatal("no DSN") }',
        imports=("os", "testing"),
    )
    result = create_service(go_project).execute("go.test")["result"]
    assert result["status"] == "success", result["summary"]


def test_failures_name_each_failing_test_with_its_output(go_project):
    write_tests(go_project, 't.Log("ok")', 't.Fatal("want 3, got 4")', 't.Error("bad input")')
    result = create_service(go_project).execute("go.test")["result"]
    assert (result["status"], result["reason"]) == ("failed", "TEST_FAILED")
    assert "example.test/check.Test1" in result["summary"]
    assert "example.test/check.Test2" in result["summary"]
    failures = {item["test"]: item for item in result["data"]["failures"]}
    assert failures.keys() == {"Test1", "Test2"}
    assert failures["Test1"]["package"] == "example.test/check"
    assert "want 3, got 4" in failures["Test1"]["output"]


def test_build_failures_report_the_package(go_project):
    write_tests(go_project, "undefinedCall()")
    result = create_service(go_project).execute("go.test")["result"]
    assert result["status"] == "failed"
    [failure] = result["data"]["failures"]
    assert failure["package"] == "example.test/check" and failure["test"] is None
    assert "undefined: undefinedCall" in failure["output"] + result["data"]["stderr"]


def test_arguments_select_packages_tests_and_build_tags(go_project):
    write_tests(go_project, 't.Log("ok")', 't.Log("ok")')
    (go_project / "sub").mkdir()
    write_tests(go_project / "sub", 't.Log("ok")')
    write_tests(
        go_project,
        't.Log("ok")',
        name="integration_test.go",
        header="//go:build integration\n\n",
        prefix="TestIntegration",
    )
    service = create_service(go_project)

    def passed(arguments):
        result = service.execute("go.test", arguments)["result"]
        assert result["status"] == "success", result["summary"]
        return result["data"]["tests"]["passed"]

    assert passed({}) == 3
    assert passed({"packages": ["./sub"]}) == 1
    assert passed({"run": "^Test1$"}) == 1
    assert passed({"tags": ["integration"]}) == 4


def test_race_detector_finds_a_data_race(go_project):
    write_tests(
        go_project,
        "n := 0; done := make(chan bool); go func() { n++; done <- true }(); n++; <-done",
    )
    assert create_service(go_project).execute("go.test")["result"]["status"] == "success"
    result = create_service(go_project).execute("go.test", {"race": True})["result"]
    assert result["status"] == "failed"
    assert "DATA RACE" in result["data"]["failures"][0]["output"]


def test_options_from_devkit_toml_apply_and_arguments_override_them(go_project):
    write_tests(go_project, 't.Log("ok")', 't.Log("ok")')
    with (go_project / "devkit.toml").open("a") as config:
        config.write('[options.go]\nrun = "^Test0$"\n')
    service = create_service(go_project)
    assert service.execute("go.test")["result"]["data"]["tests"]["passed"] == 1
    assert service.execute("go.test", {"run": "."})["result"]["data"]["tests"]["passed"] == 2


@pytest.mark.parametrize(
    "arguments",
    [{"packages": ["-exec=sh"]}, {"tags": ["a b"]}, {"race": "yes"}, {"unknown": 1}],
)
def test_invalid_arguments_are_rejected(go_project, arguments):
    result = create_service(go_project).execute("go.test", arguments)["result"]
    assert result["status"] == "error"


def test_summary_counts_failures_beyond_those_it_lists(go_project):
    write_tests(go_project, *['t.Fail()'] * 60)
    result = create_service(go_project).execute("go.test")["result"]
    assert result["summary"].endswith(", and 40 more")
    assert len(result["data"]["failures"]) == 50
