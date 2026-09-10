"""Getting a run into Langfuse, Phoenix, Datadog, W&B or MLflow.

The observability platforms are integration targets rather than rivals: they
watch production and this measures a fixture, and the useful position is being
the harness that feeds them. What that takes is less code than it looks like,
and saying so is the point of this module.

**Most of them already speak OTLP.** Langfuse, Phoenix, Datadog, Grafana Tempo
and Honeycomb all ingest OpenTelemetry, and `exporters/otel.py` already writes
GenAI spans. Five exporter classes posting the same bytes to five paths would be
five names in a listing with no new capability behind any of them -- coverage in
the docs and none in the code. So what ships for those is a **targets table**:
the endpoint path, the authentication header, and the environment variable each
platform reads the credential from. That is the part a user otherwise learns by
reading five sets of docs.

**Two of them do not.** Weights & Biases and MLflow are run-based rather than
span-based: a run with parameters, metrics and artifacts. Those get real
converters, because a span stream is not a shape either of them accepts.

**And one of them wants something OTLP cannot carry.** Langfuse models
evaluation scores as first-class objects attached to a trace, not as span
attributes -- which is exactly what this project produces and exactly what gets
lost in a plain OTLP push. `langfuse_scores` emits them.

Nothing here transmits anything. This writes files and prints the command; the
sending is the caller's decision, made with the caller's collector and network
policy. A benchmark that phoned home by default would be the wrong artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tooltrace.exporters.otel import GENAI_CONVENTIONS_VERSION


@dataclass(frozen=True)
class OtlpTarget:
    """One platform that ingests OpenTelemetry, and how to reach it."""

    name: str
    #: Appended to the platform's base URL. The `/v1/traces` suffix is the OTLP
    #: HTTP convention; a platform that deviates says so here.
    path: str
    #: The header carrying the credential. Named rather than filled: this
    #: package never holds a key.
    auth_header: str
    #: How the credential is encoded in that header, as a template.
    auth_format: str
    #: The environment variable a user is expected to keep it in.
    env_var: str
    #: What this platform does with the spans once it has them, and what it
    #: cannot do with them. The second half is the useful half.
    note: str


OTLP_TARGETS: dict[str, OtlpTarget] = {
    "langfuse": OtlpTarget(
        name="Langfuse",
        path="/api/public/otel/v1/traces",
        auth_header="Authorization",
        auth_format="Basic {base64(public_key:secret_key)}",
        env_var="LANGFUSE_AUTH",
        note=(
            "Maps spans to traces and observations. Evaluation scores are a separate "
            "object it will not infer from span attributes -- use `langfuse_scores` "
            "or every run arrives unscored"
        ),
    ),
    "phoenix": OtlpTarget(
        name="Arize Phoenix",
        path="/v1/traces",
        auth_header="api_key",
        auth_format="{api_key}",
        env_var="PHOENIX_API_KEY",
        note=(
            "Self-hostable and OTLP-native. A local Phoenix needs no credential at "
            "all, which is the easiest way to look at a trace from this project"
        ),
    ),
    "datadog": OtlpTarget(
        name="Datadog",
        path="/api/v2/otlp/v1/traces",
        auth_header="DD-API-KEY",
        auth_format="{api_key}",
        env_var="DD_API_KEY",
        note="Requires the site-specific host (datadoghq.com, datadoghq.eu, ...)",
    ),
    "honeycomb": OtlpTarget(
        name="Honeycomb",
        path="/v1/traces",
        auth_header="x-honeycomb-team",
        auth_format="{api_key}",
        env_var="HONEYCOMB_API_KEY",
        note="Wants a dataset name in `x-honeycomb-dataset` as well",
    ),
    "grafana": OtlpTarget(
        name="Grafana Cloud / Tempo",
        path="/otlp/v1/traces",
        auth_header="Authorization",
        auth_format="Basic {base64(instance_id:token)}",
        env_var="GRAFANA_OTLP_AUTH",
        note="Tempo stores spans; scores and metrics need a separate destination",
    ),
}


def push_instructions(target: str, base_url: str = "<base-url>") -> dict[str, Any]:
    """How to send an OTLP file to one platform, without sending it.

    Returns the command rather than running it. The credential is referenced by
    environment variable and never read here: a tool that loads a key in order to
    print a command has held a key it did not need.
    """
    if target not in OTLP_TARGETS:
        raise ValueError(
            f"unknown OTLP target {target!r}; expected one of {', '.join(sorted(OTLP_TARGETS))}"
        )
    spec = OTLP_TARGETS[target]
    endpoint = f"{base_url.rstrip('/')}{spec.path}"
    return {
        "target": target,
        "name": spec.name,
        "endpoint": endpoint,
        "auth_header": spec.auth_header,
        "auth_format": spec.auth_format,
        "env_var": spec.env_var,
        "note": spec.note,
        "command": (
            f'curl -X POST "{endpoint}" '
            f'-H "Content-Type: application/json" '
            f'-H "{spec.auth_header}: ${spec.env_var}" '
            f"--data-binary @otlp-spans.json"
        ),
        "conventions": GENAI_CONVENTIONS_VERSION,
    }


def langfuse_scores(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evaluation scores as Langfuse score objects.

    The thing a plain OTLP push loses. Langfuse treats a score as an object
    attached to a trace, with a name, a value and a comment -- not as a span
    attribute -- so a run exported as spans alone arrives complete and unscored,
    which looks like a working integration and is not.

    A run with no score produces no object rather than a zero: "this did not
    score" and "this scored nothing" are different, and only one of them should
    drag an average down.
    """
    scores: list[dict[str, Any]] = []
    for result in results:
        trace_id = str(result.get("run_id") or "")
        if not trace_id:
            continue
        score = result.get("score") or {}
        total = score.get("total") if isinstance(score, dict) else None
        if isinstance(total, int | float):
            scores.append(
                {
                    "traceId": trace_id,
                    "name": "tooltrace.score",
                    "value": float(total),
                    "dataType": "NUMERIC",
                    "comment": f"task {result.get('task_id')} v{result.get('task_version')}",
                }
            )
        # Success is a separate score rather than a threshold on the number
        # above: a partial success and a failure can share a total, and
        # collapsing them would hide the distinction the taxonomy exists for.
        scores.append(
            {
                "traceId": trace_id,
                "name": "tooltrace.success",
                "value": 1.0 if result.get("success") else 0.0,
                "dataType": "BOOLEAN",
                "comment": str(result.get("failure_reason") or "none"),
            }
        )
    return scores


def _numeric_metrics(result: dict[str, Any]) -> dict[str, float]:
    """Every numeric field worth charting, skipping the ones that are absent.

    A `None` is dropped rather than sent as 0. A platform cannot tell an
    unreported metric from a zero once it has stored one, and a chart of
    "model_ms" that reads zero for every scripted run is worse than a chart with
    a gap in it.
    """
    fields = (
        "steps",
        "tool_calls",
        "failed_tool_calls",
        "invalid_tool_calls",
        "unknown_parameters",
        "repeated_calls",
        "unnecessary_changes",
        "workspace_violations",
        "wall_ms",
        "model_ms",
        "tool_ms",
        "test_pass_ratio",
    )
    metrics: dict[str, float] = {}
    for field_name in fields:
        value = result.get(field_name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            metrics[field_name] = float(value)
    score = result.get("score")
    if isinstance(score, dict) and isinstance(score.get("total"), int | float):
        metrics["score_total"] = float(score["total"])
    metrics["success"] = 1.0 if result.get("success") else 0.0
    return metrics


def to_mlflow_runs(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One MLflow run per evaluation run.

    MLflow is run-based rather than span-based, so a span stream is not a shape
    it accepts and a converter is genuinely needed rather than a rename.

    Parameters are what was held fixed (the task, the agent, the versions);
    metrics are what was measured. Putting a task id in metrics or a step count
    in parameters would make both views useless, and MLflow cannot tell which is
    which on its own.
    """
    runs: list[dict[str, Any]] = []
    for result in results:
        runs.append(
            {
                "run_name": str(result.get("run_id") or ""),
                "params": {
                    "task_id": str(result.get("task_id") or ""),
                    "task_version": str(result.get("task_version") or ""),
                    "agent": str(result.get("agent") or ""),
                    "task_protocol_version": str(result.get("task_protocol_version") or ""),
                },
                "metrics": _numeric_metrics(result),
                "tags": {
                    "failure_reason": str(result.get("failure_reason") or "none"),
                    "trust_state": str(result.get("trust_state") or ""),
                    # Recorded as a tag rather than inferred later: a consumer
                    # that has to guess which harness produced a run will guess.
                    "harness": "tooltrace-bench",
                },
                "start_time": str(result.get("started_at") or ""),
                "end_time": str(result.get("finished_at") or ""),
            }
        )
    return runs


def to_wandb_records(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One `wandb.log`-shaped record per run.

    Flat, because W&B charts a flat namespace and a nested dict arrives as an
    opaque blob nobody can plot. The config/metric split is the same distinction
    MLflow needs and for the same reason.
    """
    records: list[dict[str, Any]] = []
    for result in results:
        records.append(
            {
                "name": str(result.get("run_id") or ""),
                "config": {
                    "task_id": str(result.get("task_id") or ""),
                    "task_version": str(result.get("task_version") or ""),
                    "agent": str(result.get("agent") or ""),
                    "harness": "tooltrace-bench",
                },
                "summary": _numeric_metrics(result),
                "tags": [
                    str(result.get("failure_reason") or "none"),
                    str(result.get("agent") or ""),
                ],
            }
        )
    return records


def platform_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    """What this run set looks like to each destination, and what each loses."""
    return {
        "otlp_targets": sorted(OTLP_TARGETS),
        "runs": len(results),
        "mlflow_runs": len(to_mlflow_runs(results)),
        "wandb_records": len(to_wandb_records(results)),
        "langfuse_scores": len(langfuse_scores(results)),
        "statement": (
            f"{len(results)} run(s). Five OTLP platforms take the spans "
            "`tooltrace export --format otlp` already writes; Weights & Biases and "
            "MLflow are run-based and get converted records instead. Langfuse also "
            "needs the scores, which a plain OTLP push does not carry -- without them "
            "every run arrives complete and unscored."
        ),
    }
