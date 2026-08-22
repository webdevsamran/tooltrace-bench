"""Report generation: JSON, CSV, Markdown, JUnit XML, standalone HTML.

Also hosts the exporter plugin hook: reporters registered under the
``tooltrace.reporters`` entry-point group receive the benchmark payload dict
and a destination path.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC
from pathlib import Path
from typing import Any

HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>ToolTrace Bench Report</title>
<style>
body{font-family:system-ui,sans-serif;margin:2rem;background:#0f172a;color:#e2e8f0}
h1{color:#38bdf8}table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid #334155;padding:.5rem .75rem;text-align:left}
th{background:#1e293b}.ok{color:#4ade80}.bad{color:#f87171}
pre{background:#1e293b;padding:1rem;border-radius:6px;overflow:auto}
</style></head><body>
<h1>ToolTrace Bench Report</h1>
<p>Generated @@GENERATED@@. Run: <code>@@RUN_ID@@</code></p>
<table><tr><th>Task</th><th>Agent</th><th>Success</th><th>Score</th>
<th>Steps</th><th>Tool calls</th><th>Failed</th><th>Wall ms</th><th>Failure reason</th></tr>
@@ROWS@@</table>
<h2>Summary</h2><pre>@@SUMMARY@@</pre>
@@DETAILS@@
</body></html>"""


def _rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return results


def to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def to_csv(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    fields = [
        "task_id",
        "task_version",
        "agent",
        "success",
        "partial_success",
        "score_total",
        "steps",
        "tool_calls",
        "failed_tool_calls",
        "invalid_tool_calls",
        "repeated_calls",
        "unnecessary_changes",
        "workspace_violations",
        "wall_ms",
        "model_ms",
        "tool_ms",
        "failure_reason",
        "trust_state",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in results:
        row = dict(r)
        row["score_total"] = r.get("score", {}).get("total")
        writer.writerow(row)
    return buf.getvalue()


def to_markdown(payload: dict[str, Any]) -> str:
    lines = ["# ToolTrace Bench Report", ""]
    summary = payload.get("summary") or {}
    if summary:
        lines += ["## Summary", "", "```json", json.dumps(summary, indent=2), "```", ""]
    lines += [
        "| Task | Agent | Success | Score | Steps | Tool calls | Failed | Wall ms | Failure |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in _rows(payload.get("results", [])):
        score = r.get("score", {}).get("total")
        lines.append(
            f"| {r.get('task_id')} | {r.get('agent')} "
            f"| {'yes' if r.get('success') else 'no'} | {score} "
            f"| {r.get('steps')} | {r.get('tool_calls')} | {r.get('failed_tool_calls')} "
            f"| {r.get('wall_ms')} | {r.get('failure_reason')} |"
        )
    return chr(10).join(lines) + chr(10)


def to_junit(payload: dict[str, Any]) -> str:
    """JUnit XML: one testsuite per benchmark, one testcase per result."""
    cases = []
    for r in _rows(payload.get("results", [])):
        name = f"{r.get('task_id')} [{r.get('agent')}]"
        if r.get("success"):
            case = f'    <testcase name="{name}" time="{r.get("wall_ms", 0) / 1000:.3f}"/>'
        else:
            msg = str(r.get("failure_detail", r.get("failure_reason", "failed")))[:300]
            case = (
                f'    <testcase name="{name}" time="{r.get("wall_ms", 0) / 1000:.3f}">'
                + "<failure message='task failed'>"
                + msg
                + "</failure></testcase>"
            )
        cases.append(case)
    failures = sum(1 for r in _rows(payload.get("results", [])) if not r.get("success"))
    total = len(_rows(payload.get("results", [])))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        + chr(10)
        + f'<testsuite name="tooltrace-bench" tests="{total}" failures="{failures}">'
        + chr(10)
        + chr(10).join(cases)
        + chr(10)
        + "</testsuite>"
        + chr(10)
    )


def to_html(payload: dict[str, Any]) -> str:
    rows = []
    for r in _rows(payload.get("results", [])):
        cls = "ok" if r.get("success") else "bad"
        rows.append(
            f"<tr><td>{r.get('task_id')}</td><td>{r.get('agent')}</td>"
            f'<td class="{cls}">{"PASS" if r.get("success") else "FAIL"}</td>'
            f"<td>{r.get('score', {}).get('total')}</td><td>{r.get('steps')}</td>"
            f"<td>{r.get('tool_calls')}</td><td>{r.get('failed_tool_calls')}</td>"
            f"<td>{r.get('wall_ms')}</td><td>{r.get('failure_reason')}</td></tr>"
        )
    from datetime import datetime

    details: list[str] = []
    for r in _rows(payload.get("results", [])):
        timeline = r.get("trace_timeline")
        diff = r.get("workspace_diff")
        if not timeline and not diff:
            continue
        title = f"{r.get('task_id')} [{r.get('agent')}]"
        block = [f"<h2>Detail — {title}</h2>"]
        if timeline:
            items = "".join(f"<li>{ev}</li>" for ev in timeline[:200])
            block.append(f"<h3>Trace timeline</h3><ol>{items}</ol>")
        if diff:
            import html as _html

            block.append(f"<h3>Workspace diff</h3><pre>{_html.escape(str(diff))}</pre>")
        details.append("".join(block))
    return (
        HTML_TEMPLATE.replace("@@GENERATED@@", datetime.now(UTC).isoformat())
        .replace("@@RUN_ID@@", str(payload.get("run_id", "-")))
        .replace("@@ROWS@@", chr(10).join(rows))
        .replace("@@SUMMARY@@", json.dumps(payload.get("summary", {}), indent=2)[:4000])
        .replace("@@DETAILS@@", chr(10).join(details))
    )


FORMATS = {"json": to_json, "csv": to_csv, "md": to_markdown, "junit": to_junit, "html": to_html}


def export_report(payload: dict[str, Any], fmt: str, dest: Path | None = None) -> str:
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; available: {sorted(FORMATS)}")
    text = (
        to_csv(payload.get("results", [])) if fmt == "csv" else FORMATS[fmt](payload)  # type: ignore[operator]
    )
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return text


def export_with_plugins(payload: dict[str, Any], dest_dir: Path) -> list[str]:
    """Run every registered reporter plugin; return produced file names."""
    from tooltrace.core.registry import discover_plugins

    produced: list[str] = []
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name, plugin in discover_plugins("tooltrace.reporters").items():
        try:
            out = plugin(payload, dest_dir)
            produced.append(str(out))
        except Exception as exc:
            produced.append(f"{name}: ERROR {exc}")
    return produced
