"""External trace ingestion: score *anyone's* traces with ToolTrace.

Converts traces produced outside this harness into versioned
:class:`tooltrace.core.models.TraceEvent` streams so they can be classified
with the failure taxonomy, replayed, diffed and scored by the standard
pipeline. Supported formats:

- ``otel-spans``  — OpenTelemetry GenAI semantic-convention span dicts
  (``gen_ai.tool.name``, ``gen_ai.request.model``, ...). This turns
  observability data from LangGraph / OpenAI Agents SDK / OTel-instrumented
  apps into evaluable trajectories.
- ``openai-steps`` — plain assistant-step records (message content +
  ``tool_calls``), i.e. what any OpenAI-compatible request log already stores.

Ingestion is deliberately lossy-but-honest: events that have no ToolTrace
equivalent are summarized as ``agent_message`` payloads; nothing is invented.
"""

from __future__ import annotations

from tooltrace.ingest.external import (
    format_counts,
    from_openai_steps,
    from_otel_spans,
)

__all__ = [
    "format_counts",
    "from_openai_steps",
    "from_otel_spans",
]
