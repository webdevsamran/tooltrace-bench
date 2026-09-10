"""Feeding the observability platforms, and being honest about how little it takes.

The platforms are integration targets rather than rivals -- they watch production
and this measures a fixture -- and most of them already speak OTLP, which
`exporters/otel.py` already writes. Five exporter classes posting the same bytes
to five paths would be five names in a listing with no new capability behind any
of them, which is the same argument that kept five local model servers on one
adapter.

So the tests below are mostly about the two things that are *not* renames:

- W&B and MLflow are run-based rather than span-based, so a span stream is not a
  shape either accepts and a real converter is needed.
- Langfuse models an evaluation score as an object attached to a trace, not as a
  span attribute. A run pushed as spans alone arrives complete and **unscored**,
  which looks like a working integration and is not.

And one thing that must never happen: nothing here transmits, and nothing here
reads a credential.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from tooltrace.exporters.platforms import (
    OTLP_TARGETS,
    langfuse_scores,
    platform_report,
    push_instructions,
    to_mlflow_runs,
    to_wandb_records,
)


def result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "r-1",
        "task_id": "p/one",
        "task_version": "1.0.0",
        "task_protocol_version": 1,
        "agent": "scripted",
        "success": True,
        "score": {"total": 0.75},
        "steps": 4,
        "tool_calls": 3,
        "failed_tool_calls": 0,
        "wall_ms": 12.5,
        "model_ms": None,
        "failure_reason": "none",
        "trust_state": "LOCAL",
        "started_at": "2026-09-10T00:00:00Z",
        "finished_at": "2026-09-10T00:00:01Z",
    }
    base.update(overrides)
    return base


# --- the thing OTLP loses ---------------------------------------------------


def test_a_score_becomes_a_langfuse_score_object() -> None:
    """A span attribute is not a score, and Langfuse will not infer one."""
    scores = langfuse_scores([result()])
    numeric = next(s for s in scores if s["name"] == "tooltrace.score")
    assert numeric["value"] == 0.75
    assert numeric["traceId"] == "r-1"


def test_success_is_a_separate_score_from_the_total() -> None:
    """A partial success and a failure can share a total.

    Collapsing them into a threshold on one number would hide exactly the
    distinction the failure taxonomy exists to draw.
    """
    scores = langfuse_scores([result(success=False, score={"total": 0.75})])
    success = next(s for s in scores if s["name"] == "tooltrace.success")
    assert success["value"] == 0.0
    assert next(s for s in scores if s["name"] == "tooltrace.score")["value"] == 0.75


def test_an_unscored_run_produces_no_numeric_score_rather_than_zero() -> None:
    """ "Did not score" and "scored nothing" are different, and only one should
    drag an average down."""
    scores = langfuse_scores([result(score={})])
    assert not [s for s in scores if s["name"] == "tooltrace.score"]
    assert [s for s in scores if s["name"] == "tooltrace.success"]


def test_a_run_with_no_id_is_skipped_rather_than_given_an_empty_trace() -> None:
    assert langfuse_scores([result(run_id="")]) == []


def test_the_failure_reason_travels_with_the_score() -> None:
    scores = langfuse_scores([result(success=False, failure_reason="tool_error")])
    assert any("tool_error" in str(s.get("comment")) for s in scores)


# --- run-based platforms ----------------------------------------------------


def test_mlflow_separates_what_was_held_fixed_from_what_was_measured() -> None:
    """A task id in metrics or a step count in params makes both views useless,
    and MLflow cannot tell which is which on its own."""
    run = to_mlflow_runs([result()])[0]
    assert run["params"]["task_id"] == "p/one"
    assert "task_id" not in run["metrics"]
    assert run["metrics"]["steps"] == 4.0
    assert "steps" not in run["params"]


def test_mlflow_carries_the_score_and_the_outcome_as_metrics() -> None:
    run = to_mlflow_runs([result()])[0]
    assert run["metrics"]["score_total"] == 0.75
    assert run["metrics"]["success"] == 1.0


def test_an_unreported_metric_is_omitted_rather_than_sent_as_zero() -> None:
    """A platform cannot tell an unreported metric from a zero once stored.

    A chart of `model_ms` reading zero for every scripted run is worse than one
    with a gap in it.
    """
    run = to_mlflow_runs([result(model_ms=None)])[0]
    assert "model_ms" not in run["metrics"]
    assert "model_ms" in to_mlflow_runs([result(model_ms=9.0)])[0]["metrics"]


def test_success_is_a_metric_not_a_metric_named_true() -> None:
    """`success` is a bool, and bool is a subclass of int in Python.

    Left alone it would be collected by the numeric sweep as 1/0 twice, once
    under its own name and once by accident.
    """
    metrics = to_mlflow_runs([result()])[0]["metrics"]
    assert metrics["success"] == 1.0
    assert all(isinstance(v, float) for v in metrics.values())


def test_wandb_records_are_flat() -> None:
    """W&B charts a flat namespace; a nested dict arrives as an unplottable blob."""
    record = to_wandb_records([result()])[0]
    assert all(not isinstance(v, dict) for v in record["summary"].values())


def test_wandb_and_mlflow_agree_on_the_numbers() -> None:
    """Two converters that disagree would make the platform the variable."""
    assert to_wandb_records([result()])[0]["summary"] == to_mlflow_runs([result()])[0]["metrics"]


def test_both_record_which_harness_produced_the_run() -> None:
    """A consumer that has to guess which harness produced a run will guess."""
    assert to_mlflow_runs([result()])[0]["tags"]["harness"] == "tooltrace-bench"
    assert to_wandb_records([result()])[0]["config"]["harness"] == "tooltrace-bench"


# --- the OTLP targets table -------------------------------------------------


def test_every_target_names_the_environment_variable_and_not_a_key() -> None:
    """A tool that loads a credential in order to print a command has held one
    it did not need."""
    for name in OTLP_TARGETS:
        payload = push_instructions(name, "https://example.test")
        assert payload["env_var"]
        assert f"${payload['env_var']}" in payload["command"]


def test_the_printed_command_sends_nothing_by_itself() -> None:
    payload = push_instructions("phoenix", "http://localhost:6006")
    assert payload["command"].startswith("curl ")
    assert payload["endpoint"] == "http://localhost:6006/v1/traces"


def test_a_trailing_slash_does_not_produce_a_double_slash() -> None:
    payload = push_instructions("phoenix", "http://localhost:6006/")
    assert "//v1" not in payload["endpoint"]


def test_every_target_says_what_it_cannot_do_with_the_spans() -> None:
    """The second half of the note is the useful half."""
    for name, spec in OTLP_TARGETS.items():
        assert spec.note, f"{name} has no note"


def test_langfuse_warns_that_spans_alone_arrive_unscored() -> None:
    assert "unscored" in OTLP_TARGETS["langfuse"].note


def test_an_unknown_target_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown OTLP target"):
        push_instructions("splunk")


# --- the CLI ----------------------------------------------------------------


def test_the_cli_writes_every_conversion(tmp_path, capsys) -> None:
    from pathlib import Path

    from tooltrace.cli.main import main

    bundles = Path("results")
    if not any(bundles.glob("*.tooltrace")):  # pragma: no cover - published bundles ship
        pytest.skip("no published bundles in this checkout")
    assert main(["platforms", "--bundles", str(bundles), "--out", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    names = {Path(p).name for p in payload["written"]}
    assert names == {
        "otlp-spans.json",
        "langfuse-scores.json",
        "mlflow-runs.json",
        "wandb-records.json",
    }


def test_the_cli_prints_no_credential(tmp_path, capsys) -> None:
    from pathlib import Path

    from tooltrace.cli.main import main

    bundles = Path("results")
    if not any(bundles.glob("*.tooltrace")):  # pragma: no cover
        pytest.skip("no published bundles in this checkout")
    main(
        [
            "platforms",
            "--bundles",
            str(bundles),
            "--out",
            str(tmp_path),
            "--target",
            "datadog",
            "--base-url",
            "https://api.datadoghq.eu",
        ]
    )
    out = capsys.readouterr().out
    assert "$DD_API_KEY" in out, "the variable is named"
    assert "DD-API-KEY: " not in out.replace("DD-API-KEY: $DD_API_KEY", ""), "and never expanded"


def test_the_report_counts_what_it_produced() -> None:
    report = platform_report([result(), result(run_id="r-2")])
    assert report["runs"] == 2
    assert report["mlflow_runs"] == 2
    assert report["wandb_records"] == 2
    assert report["langfuse_scores"] == 4, "one score and one success per run"
