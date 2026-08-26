"""Targeted tests raising coverage of CLI, SDK, repro, security, scoring,
perturbations, failure classification and remaining adapters."""

from __future__ import annotations

import subprocess
import sys

from tooltrace.core.models import TraceEvent


def _ev(type_: str, payload: dict) -> TraceEvent:
    return TraceEvent(timestamp="t", seq=1, type=type_, payload=payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------


class TestScorersDirect:
    def test_json_schema_and_equals(self, tmp_path) -> None:
        from tooltrace.scoring.builtin import _json_equals, _json_schema

        ws = tmp_path
        (ws / "data.json").write_text('{"a": 1}', encoding="utf-8")
        out = _json_schema({"path": "data.json", "schema": {"type": "object"}}, ws)
        assert out.score == 1.0
        bad = _json_schema({"path": "data.json", "schema": {"type": "array"}}, ws)
        assert bad.score == 0.0
        eq = _json_equals({"path": "data.json", "expected": {"a": 1}}, ws)
        assert eq.score == 1.0
        ne = _json_equals({"path": "data.json", "expected": {"a": 2}}, ws)
        assert ne.score == 0.0

    def test_csv_equals(self, tmp_path) -> None:
        from tooltrace.scoring.builtin import _csv_equals

        ws = tmp_path
        (ws / "out.csv").write_text("a,b" + chr(10) + "1,2" + chr(10), encoding="utf-8")
        ok = _csv_equals(
            {
                "path": "out.csv",
                "expected_csv": "a,b" + chr(13) + chr(10) + "1,2" + chr(13) + chr(10),
            },
            ws,
        )
        assert ok.score == 1.0
        bad = _csv_equals(
            {"path": "out.csv", "expected_csv": "a,b" + chr(10) + "9,9" + chr(10)}, ws
        )
        assert bad.score == 0.0

    def test_command_exit(self, tmp_path) -> None:
        from tooltrace.scoring.builtin import _command_exit

        ok = _command_exit(
            {"command": f'"{sys.executable}" -c "print(1)"', "expect_code": 0}, tmp_path
        )
        assert ok.score == 1.0
        bad = _command_exit(
            {"command": f'"{sys.executable}" -c "raise SystemExit(3)"', "expect_code": 0}, tmp_path
        )
        assert bad.score == 0.0

    def test_tests_pass_scorer(self, tmp_path) -> None:
        from tooltrace.scoring.builtin import _tests_pass

        ws = tmp_path
        (ws / "test_ok.py").write_text(
            "def test_x():" + chr(10) + "    assert True" + chr(10), encoding="utf-8"
        )
        out = _tests_pass({"path": "."}, ws)
        assert out.score == 1.0 and "passed=1" in out.detail

    def test_git_diff_scorer(self, tmp_path) -> None:
        from tooltrace.scoring.builtin import _git_diff

        ws = tmp_path
        subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.name", "t"], check=True)
        (ws / "f.txt").write_text("one" + chr(10), encoding="utf-8")
        subprocess.run(["git", "-C", str(ws), "add", "."], check=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-qm", "init"], check=True)
        (ws / "f.txt").write_text("two" + chr(10), encoding="utf-8")

        ok = _git_diff({"contains": ["f.txt"]}, ws)
        assert ok.score == 1.0
        bad = _git_diff({"not_contains": ["f.txt"]}, ws)
        assert bad.score == 0.0

    def test_ast_check(self, tmp_path) -> None:
        from tooltrace.scoring.builtin import _ast_check

        ws = tmp_path
        (ws / "m.py").write_text("def foo():" + chr(10) + "    pass" + chr(10), encoding="utf-8")
        ok = _ast_check({"path": "m.py", "defines": ["foo"]}, ws)
        assert ok.score == 1.0
        missing = _ast_check({"path": "m.py", "defines": ["bar"]}, ws)
        assert missing.score == 0.0
        syntax_err = _ast_check({"path": "missing.py"}, ws)
        assert syntax_err.score == 0.0

    def test_data_equals_and_api_state(self, tmp_path) -> None:
        from tooltrace.scoring.builtin import _api_state, _data_equals

        ws = tmp_path
        (ws / "g.txt").write_text("hello" + chr(10), encoding="utf-8")
        assert _data_equals({"path": "g.txt", "expected": "hello"}, ws).score == 1.0
        (ws / "state.json").write_text('{"items": [{"id": 7}]}', encoding="utf-8")
        ok = _api_state({"file": "state.json", "json_path": "items.0.id", "equals": 7}, ws)
        assert ok.score == 1.0
        miss = _api_state({"file": "state.json", "json_path": "items.5.id", "equals": 7}, ws)
        assert miss.score == 0.0


# ---------------------------------------------------------------------------


class TestProcessTools:
    def test_git_tool(self, workspace) -> None:
        from tooltrace.core.registry import tool_registry
        from tooltrace.tools.base import ToolContext

        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        git = tool_registry.get("git")()
        r = git.run({"args": ["status", "--short"]}, ToolContext(workspace=workspace))
        assert r.ok and r.data["exit_code"] == 0
        blocked = git.run({"args": ["push", "origin", "main"]}, ToolContext(workspace=workspace))
        assert not blocked.ok and blocked.data.get("blocked_subcommand") == "push"

    def test_test_runner_tool(self, workspace) -> None:
        from tooltrace.core.registry import tool_registry
        from tooltrace.tools.base import ToolContext

        (workspace / "test_hi.py").write_text(
            "def test_hi():" + chr(10) + "    assert 1" + chr(10), encoding="utf-8"
        )
        tr = tool_registry.get("test_runner")()
        r = tr.run({"path": "."}, ToolContext(workspace=workspace))
        assert r.ok and r.data["passed"] >= 1
        unsupported = tr.run({"framework": "unittest"}, ToolContext(workspace=workspace))
        assert not unsupported.ok


# ---------------------------------------------------------------------------


class TestHttpTool:
    def test_allowlisted_request(self, workspace, monkeypatch) -> None:
        import httpx
        from tooltrace.core.registry import tool_registry
        from tooltrace.tools.base import ToolContext

        class FakeResp:
            status_code = 200
            is_success = True
            text = '{"ok": true}'

            def __init__(self) -> None:
                self.headers = {"content-type": "application/json"}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def request(self, *a, **k):
                return FakeResp()

        monkeypatch.setattr(httpx, "Client", FakeClient)
        ctx = ToolContext(
            workspace=workspace, network_policy="allowlisted", http_allowlist=["api.example.com"]
        )
        http = tool_registry.get("http")()
        r = http.run({"url": "https://api.example.com/v1/ping"}, ctx)
        assert r.ok and r.data["status_code"] == 200

        denied_host = http.run({"url": "https://evil.example.com/x"}, ctx)
        assert not denied_host.ok and denied_host.data.get("denied")

        bad_method = http.run({"url": "https://api.example.com/x", "method": "TRACE"}, ctx)
        assert not bad_method.ok
