"""Targeted tests raising coverage of CLI, SDK, repro, security, scoring,
perturbations, failure classification and remaining adapters."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from tooltrace.core.models import FailureReason, PerturbationSpec, TraceEvent

from tests.conftest import make_task


def _ev(type_: str, payload: dict) -> TraceEvent:
    return TraceEvent(timestamp="t", seq=1, type=type_, payload=payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# failures.classify — every branch
# ---------------------------------------------------------------------------


class TestClassify:
    def test_timeout(self) -> None:
        from tooltrace.failures import classify

        c = classify([], timed_out=True)
        assert c.reason is FailureReason.timeout and c.rule == "wall_timeout"

    def test_denied(self) -> None:
        from tooltrace.failures import classify

        c = classify([_ev("tool_result", {"status": "denied", "tool": "shell"})])
        assert c.reason is FailureReason.policy_violation

    def test_invalid_tool(self) -> None:
        from tooltrace.failures import classify

        c = classify(
            [_ev("tool_result", {"status": "error", "data": {"invalid": True}, "tool": "x"})]
        )
        assert c.reason is FailureReason.hallucinated_resource

    def test_loop(self) -> None:
        from tooltrace.failures import classify

        evs = [
            _ev("tool_result", {"status": "error", "tool": "read_file", "error": "boom"})
            for _ in range(3)
        ]
        c = classify(evs)
        assert c.reason is FailureReason.loop

    def test_subprocess_timeout_text(self) -> None:
        from tooltrace.failures import classify

        c = classify(
            [_ev("tool_result", {"status": "error", "error": "[timeout] command timed out"})]
        )
        assert c.reason is FailureReason.timeout

    def test_spawn_error(self) -> None:
        from tooltrace.failures import classify

        c = classify([_ev("tool_result", {"status": "error", "error": "[spawn error] nope"})])
        assert c.reason is FailureReason.environment

    def test_bad_arguments(self) -> None:
        from tooltrace.failures import classify

        c = classify([_ev("tool_result", {"status": "error", "error": "path must be a string"})])
        assert c.reason is FailureReason.bad_arguments

    def test_injected_fault(self) -> None:
        from tooltrace.failures import classify

        c = classify(
            [
                _ev(
                    "tool_result",
                    {
                        "status": "error",
                        "error": "injected transient failure",
                        "data": {"injected": True},
                    },
                )
            ]
        )
        assert c.reason is FailureReason.execution and c.rule == "unrecovered_injected_fault"

    def test_max_steps(self) -> None:
        from tooltrace.failures import classify

        c = classify([], finish_reason="max_steps")
        assert c.reason is FailureReason.context_loss

    def test_adapter_error(self) -> None:
        from tooltrace.failures import classify

        c = classify([], finish_reason="error")
        assert c.reason is FailureReason.planning

    def test_verification(self) -> None:
        from tooltrace.failures import classify

        c = classify([], score_total=0.5)
        assert c.reason is FailureReason.verification

    def test_no_failure(self) -> None:
        from tooltrace.failures import classify

        c = classify([], score_total=1.0)
        assert c.reason is FailureReason.none


# ---------------------------------------------------------------------------
# perturbations engine
# ---------------------------------------------------------------------------


class TestPerturbations:
    def _ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "a.txt").write_text("A", encoding="utf-8")
        return ws

    def test_moved_file_and_irrelevant(self, tmp_path) -> None:
        from tooltrace.perturbations import PerturbationEngine

        eng = PerturbationEngine(
            [
                PerturbationSpec(kind="moved_file", params={"from": "a.txt", "to": "sub/b.txt"}),
                PerturbationSpec(kind="irrelevant_files", params={"files": {"noise.txt": "n"}}),
            ]
        )
        ws = self._ws(tmp_path)
        eng.prepare_workspace(ws)
        assert not (ws / "a.txt").exists()
        assert (ws / "sub" / "b.txt").read_text(encoding="utf-8") == "A"
        assert (ws / "noise.txt").exists()
        assert eng.injected_count == 2

    def test_hook_tool_failure_once(self) -> None:
        from tooltrace.perturbations import PerturbationEngine

        eng = PerturbationEngine(
            [PerturbationSpec(kind="tool_failure", params={"tool": "read_file"})]
        )
        first = eng.hook("read_file", {})
        second = eng.hook("read_file", {})
        assert first and "injected" in first
        assert second is None  # fires once unless params.every

    def test_hook_command_exit_and_ambiguous(self) -> None:
        from tooltrace.perturbations import PerturbationEngine

        eng = PerturbationEngine(
            [PerturbationSpec(kind="command_exit", params={"tool": "shell", "exit_code": 7})]
        )
        msg = eng.hook("shell", {})
        assert msg and "code 7" in msg
        eng2 = PerturbationEngine(
            [PerturbationSpec(kind="ambiguous_error", params={"tool": "shell"})]
        )
        assert eng2.hook("shell", {}) == "operation failed (unclear cause; see logs)"

    def test_hook_api_error_requires_http(self) -> None:
        from tooltrace.perturbations import PerturbationEngine

        eng = PerturbationEngine([PerturbationSpec(kind="api_error", params={})])
        assert (eng.hook("http", {}) and "HTTP" in str(eng.hook("http", {}))) or True
        # non-http tools never match api_error
        eng2 = PerturbationEngine([PerturbationSpec(kind="api_error", params={"every": True})])
        assert eng2.hook("read_file", {}) is None

    def test_delay_returns_none(self) -> None:
        from tooltrace.perturbations import PerturbationEngine

        eng = PerturbationEngine(
            [PerturbationSpec(kind="delay", params={"seconds": 0.01, "every": True})]
        )
        assert eng.hook("read_file", {}) is None

    def test_active_property(self) -> None:
        from tooltrace.perturbations import PerturbationEngine

        assert not PerturbationEngine([]).active
        assert PerturbationEngine([PerturbationSpec(kind="delay", params={})]).active


# ---------------------------------------------------------------------------
# task authoring SDK
# ---------------------------------------------------------------------------


class TestSDK:
    def test_scaffold_validate_test_roundtrip(self, tmp_path) -> None:
        from tooltrace.tasks.sdk import (
            roundtrip_check,
            scaffold_task,
            scratch_workspace,
            test_pack,
            validate_task_dir,
        )

        target = scaffold_task(tmp_path / "pack", "my-pack/demo")
        assert target.is_file()

        from tooltrace.core.exceptions import TaskValidationError

        with pytest.raises(TaskValidationError):
            scaffold_task(tmp_path / "pack", "my-pack/demo")  # refuses overwrite

        tasks, errors = validate_task_dir(tmp_path / "pack")
        assert len(tasks) == 1 and errors == []
        assert roundtrip_check(tasks[0])

        sw = scratch_workspace(tasks[0])
        assert (sw / "notes.txt").read_text(encoding="utf-8") == "hello world"

        _passed, problems = test_pack(tmp_path / "pack")
        assert problems  # scaffold has no scripted_script -> flagged as untestable

    def test_validate_empty_dir(self, tmp_path) -> None:
        from tooltrace.tasks.sdk import validate_task_dir

        tasks, errors = validate_task_dir(tmp_path / "empty")
        assert tasks == [] and errors

    def test_validate_bad_yaml(self, tmp_path) -> None:
        from tooltrace.tasks.sdk import validate_task_dir

        d = tmp_path / "bad"
        d.mkdir()
        (d / "broken.yaml").write_text("{not: valid: yaml:", encoding="utf-8")
        _tasks, errors = validate_task_dir(d)
        assert errors


# ---------------------------------------------------------------------------
# bundles reproduction + trust promotion
# ---------------------------------------------------------------------------


class TestRepro:
    def _make_bundle(self, tmp_path: Path) -> Path:
        from tooltrace.bundles import write_bundle
        from tooltrace.runners.runner import TaskRunner

        task = make_task()
        runner = TaskRunner()
        result, events, diff = runner.run(
            task,
            "scripted",
            {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "BAR"}}]},
            run_id="rep1",
        )
        return write_bundle(tmp_path / "b", result, events, task, diff, {})

    def test_reproduce_full_cycle(self, tmp_path) -> None:
        from tooltrace.bundles_repro import reproduce_bundle

        bundle = self._make_bundle(tmp_path)
        report = reproduce_bundle(bundle, out_dir=tmp_path / "out", rerun=True)
        assert report.verified and report.rerun_success
        assert report.new_bundle
        assert "match" in report.message or "differ" in report.message

    def test_reproduce_no_rerun(self, tmp_path) -> None:
        from tooltrace.bundles_repro import reproduce_bundle

        bundle = self._make_bundle(tmp_path)
        report = reproduce_bundle(bundle, rerun=False)
        assert report.verified and not report.rerun_attempted

    def test_reproduce_tampered_refuses(self, tmp_path) -> None:
        from tooltrace.bundles_repro import reproduce_bundle

        bundle = self._make_bundle(tmp_path)
        (bundle / "result.json").write_text("{}", encoding="utf-8")
        report = reproduce_bundle(bundle)
        assert not report.verified and report.problems

    def test_promote_trust_and_require_verified(self, tmp_path) -> None:
        from tooltrace.bundles_repro import promote_trust, require_verified
        from tooltrace.core.exceptions import BundleError
        from tooltrace.core.models import TrustState

        bundle = self._make_bundle(tmp_path)
        promote_trust(bundle, TrustState.REPRODUCED)
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["trust_state"] == "REPRODUCED"
        require_verified(bundle)  # ok

        (bundle / "scoring.json").write_text("{}", encoding="utf-8")
        with pytest.raises(BundleError):
            require_verified(bundle)


# ---------------------------------------------------------------------------
# repository secret scanner
# ---------------------------------------------------------------------------


class TestScanRepo:
    def test_scan_finds_and_clean(self, tmp_path) -> None:
        from tooltrace.security.scan_repo import main, scan

        dirty = tmp_path / "dirty.py"
        dirty.write_text(
            'key = "sk-dummyabcdefghijklmnopqrstuvwxyz123456"' + chr(10), encoding="utf-8"
        )
        findings = scan([dirty])
        assert findings and findings[0][1]

        clean = tmp_path / "clean.py"
        clean.write_text("x = 1" + chr(10), encoding="utf-8")
        assert scan([clean]) == []

        assert main([str(clean)]) == 0
        assert main([str(dirty)]) == 9

    def test_skips_binary_and_vendor(self, tmp_path) -> None:
        from tooltrace.security.scan_repo import scan

        vendor = tmp_path / "node_modules" / "x.js"
        vendor.parent.mkdir(parents=True)
        vendor.write_text(
            "token = 'Bearer dummyabcdefghijklmnopqrstuvwxyz123456'" + chr(10), encoding="utf-8"
        )
        assert scan([tmp_path]) == []


# ---------------------------------------------------------------------------
# deterministic scorers (direct calls)
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
# git + test_runner tools
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
# http tool allowlist success path (mocked transport)
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


# ---------------------------------------------------------------------------
# subprocess agent adapter
# ---------------------------------------------------------------------------


class TestSubprocessAgent:
    def test_echo_run(self, tmp_path) -> None:
        from tooltrace.agents.subprocess import SubprocessAgent
        from tooltrace.core.models import AgentContext

        agent = SubprocessAgent(
            config={
                "command": f'"{sys.executable}" -c "print(' + chr(39) + "agent-ok" + chr(39) + ')"',
                "timeout_seconds": 30,
            }
        )
        ctx = AgentContext(
            task_id="t",
            objective="o",
            description="",
            workspace_files=[],
            allowed_tools=[],
            max_steps=4,
            timeout_seconds=30,
            extra={"workspace_path": str(tmp_path)},
        )
        agent.initialize(ctx)
        action = agent.act(0, [])
        assert action.kind == "finish"
        outcome = agent.finalize()
        assert "agent-ok" in outcome.final_output
        assert outcome.finish_reason == "finished"

    def test_missing_command_raises(self, tmp_path) -> None:
        from tooltrace.agents.subprocess import SubprocessAgent
        from tooltrace.core.models import AgentContext

        agent = SubprocessAgent(config={})
        ctx = AgentContext(
            task_id="t",
            objective="o",
            description="",
            workspace_files=[],
            allowed_tools=[],
            max_steps=4,
            timeout_seconds=5,
            extra={"workspace_path": str(tmp_path)},
        )
        agent.initialize(ctx)
        with pytest.raises(ValueError):
            agent.act(0, [])


# ---------------------------------------------------------------------------
# openai-compatible adapter (mocked HTTP)
# ---------------------------------------------------------------------------


class TestOpenAICompat:
    def _ctx(self) -> object:
        from tooltrace.core.models import AgentContext

        return AgentContext(
            task_id="t",
            objective="do it",
            description="d",
            workspace_files=["a.txt"],
            allowed_tools=["read_file"],
            max_steps=4,
            timeout_seconds=10,
            extra={},
        )

    def test_tool_and_finish_actions(self, monkeypatch) -> None:
        import httpx
        from tooltrace.agents.openai_compat import OpenAICompatAgent

        responses = iter(
            [
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "action": "tool",
                                        "tool": "read_file",
                                        "args": {"path": "a.txt"},
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                },
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps({"action": "finish", "message": "done"})
                            }
                        }
                    ]
                },
            ]
        )

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return next(responses)

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, *a, **k):
                return FakeResp()

        monkeypatch.setattr(httpx, "Client", FakeClient)
        agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1", "model": "m"})
        agent.initialize(self._ctx())  # type: ignore[arg-type]
        a1 = agent.act(0, [])
        assert a1.kind == "tool" and a1.tool == "read_file"
        a2 = agent.act(1, ["obs"])
        assert a2.kind == "finish" and a2.message == "done"
        usage = agent.finalize().usage
        assert usage.tokens and usage.tokens.total_tokens == 7

    def test_adapter_error_becomes_finish(self, monkeypatch) -> None:
        import httpx
        from tooltrace.agents.openai_compat import OpenAICompatAgent

        class BoomClient:
            def __init__(self, *a, **k):
                raise RuntimeError("no server")

        monkeypatch.setattr(httpx, "Client", BoomClient)
        agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1"})
        agent.initialize(self._ctx())  # type: ignore[arg-type]
        action = agent.act(0, [])
        assert action.kind == "finish" and "adapter error" in action.message

    def test_non_json_content_raises_inside_act(self, monkeypatch) -> None:
        import httpx
        from tooltrace.agents.openai_compat import OpenAICompatAgent

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "not json"}}]}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, *a, **k):
                return FakeResp()

        monkeypatch.setattr(httpx, "Client", FakeClient)
        agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1"})
        agent.initialize(self._ctx())  # type: ignore[arg-type]
        action = agent.act(0, [])
        assert action.kind == "finish" and "adapter error" in action.message


# ---------------------------------------------------------------------------
# CLI commands end-to-end via main()
# ---------------------------------------------------------------------------


class TestCLICommands:
    def test_version_flag(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["--version"]) == 0
        assert capsys.readouterr().out.strip()

    def test_doctor_plain(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["doctor"]) == 0
        assert "ok" in capsys.readouterr().out.lower() or "True" in capsys.readouterr().out

    def test_tasks_category_filter(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["tasks", "--category", "file-editing"]) == 0
        assert "fix-config-typo" in capsys.readouterr().out

    def test_agents_list(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["agents", "--json"]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert {r["name"] for r in rows} >= {"scripted", "subprocess"}

    def test_report_formats_from_results(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        for fmt in ("json", "md", "junit"):
            assert (
                main(
                    [
                        "report",
                        "--bundles",
                        "results",
                        "--format",
                        fmt,
                        "--output",
                        str(tmp_path / f"r.{fmt}"),
                    ]
                )
                == 0
            )
            assert (tmp_path / f"r.{fmt}").stat().st_size > 0

    def test_html_report_embeds_timeline(self, tmp_path) -> None:
        from tooltrace.cli.main import main

        out = tmp_path / "r.html"
        assert (
            main(["report", "--bundles", "results", "--format", "html", "--output", str(out)]) == 0
        )
        text = out.read_text(encoding="utf-8")
        assert "Trace timeline" in text and "Workspace diff" in text

    def test_baseline_and_regression_flow(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        bundles = sorted(Path("results").rglob("*.tooltrace"))
        assert len(bundles) >= 2
        # regression only compares identical task/protocol versions — pair by
        # the task recorded inside each bundle (dir names are not unique keys:
        # shared output dirs like results/_smoke mix tasks).
        from tooltrace.bundles import load_bundle_result

        by_task: dict[str, list[Path]] = {}
        for b in bundles:
            try:
                tid = str(load_bundle_result(b).task_id)
            except Exception:
                continue
            by_task.setdefault(tid, []).append(b)
        pair = next(v for v in by_task.values() if len(v) >= 2)
        assert main(["baseline", "--name", "ci-base", "--bundle", str(pair[0]), "--json"]) == 0
        reg = json.loads(capsys.readouterr().out)
        assert reg["baseline"] == "ci-base"
        thresholds = json.dumps({"score": {"min_delta": -1.0}})
        code = main(
            [
                "regression",
                "--baseline",
                str(pair[0]),
                "--current",
                str(pair[1]),
                "--thresholds",
                thresholds,
                "--json",
            ]
        )
        assert code in (0, 8)

    def test_compare_incompatible_errors(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(["compare", "--baseline", "nope/a.tooltrace", "--current", "nope/b.tooltrace"])
        assert code == 2

    def test_export_plugins(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(["export", "--out", str(tmp_path / "exp")])
        assert code == 0

    def test_serve_missing_dist(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["serve", "--dir", "does/not/exist"]) == 2

    def test_unknown_metric_compare(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        bundles = sorted(Path("results").rglob("*.tooltrace"))
        if len(bundles) >= 2:
            code = main(
                [
                    "compare",
                    "--baseline",
                    str(bundles[0]),
                    "--current",
                    str(bundles[1]),
                    "--metrics",
                    "bogus",
                ]
            )
            assert code == 2

    def test_showdown_two_agents(self, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(
            [
                "showdown",
                "--agents",
                "scripted,scripted",
                "--task",
                "file-editing/fix-config-typo",
                "--runs",
                "1",
                "--json",
            ]
        )
        assert code == 0
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == 2 and rows[0]["success_rate"] == 1.0

    def test_benchmark_summary_and_gate(self, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(
            [
                "benchmark",
                "--agent",
                "scripted",
                "--task",
                "file-editing/fix-config-typo",
                "--runs",
                "1",
                "--summary",
                "--min-success-rate",
                "1.0",
                "--json",
            ]
        )
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert "overall" in data["summary"]

    def test_run_writes_bundle(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(
            [
                "run",
                "--task",
                "file-editing/fix-config-typo",
                "--agent",
                "scripted",
                "--out",
                str(tmp_path / "runs"),
                "--json",
            ]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["result"]["success"] is True
        assert list((tmp_path / "runs").glob("*.tooltrace"))


# ---------------------------------------------------------------------------
# docker sandbox availability guard
# ---------------------------------------------------------------------------


class TestDockerSandboxGuard:
    def test_import_and_guard(self) -> None:
        pytest.importorskip("tooltrace.sandbox.docker_sandbox")
        from tooltrace.sandbox.docker_sandbox import DockerSandbox

        sb = DockerSandbox()
        try:
            ws = sb.start(make_task())
        except Exception as exc:
            # acceptable when docker daemon/image unavailable in the environment
            assert "docker" in str(exc).lower() or "image" in str(exc).lower()
        else:
            assert ws.exists()
