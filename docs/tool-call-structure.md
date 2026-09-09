# Tool-call structure scoring

Two kinds of scorer run in this project.

**Workspace scorers** take `(params, workspace)` and read the final state of the
filesystem. All fifteen original scorers are this kind, and it is the right
default: it is what lets a third party recompute a score from a bundle alone.

**Trace scorers** take `(params, trace)` and read the trajectory — which tools
were called, with what arguments, in what order. They exist because an entire
class of question is inexpressible against a workspace. "Did the agent read the
file before overwriting it?" cannot be answered from the file.

## The scorers

| Type | Asks |
|---|---|
| `tool_call_match` | Do the expected calls appear, structurally, in order? |
| `tools_used` | Which tools were used at all, required and forbidden? |
| `no_failed_calls` | Did every call succeed, within a declared tolerance? |

`tool_call_match` compares a recorded call against an expectation by name,
argument names and argument types, executing nothing:

```yaml
- type: tool_call_match
  params:
    ordered: true
    expected:
      - tool: read_file
        args: { path: "string" }
      - tool: write_file
        args: { path: "string", content: "string" }
```

An argument constraint is a JSON-ish type name (`string`, `number`, `integer`,
`boolean`, `array`, `object`), an exact value, or `{type, equals}`. `bool` is
rejected where `integer` is required, despite subclassing `int` in Python.

## Attribution, and what this is not

The structural approach is modelled on the **Berkeley Function-Calling
Leaderboard** (Gorilla, UC Berkeley), which matches an emitted call against an
expected signature without executing it, and is the de-facto standard for the
question "did the model call the tool correctly". That technique is worth
adopting rather than competing with, and this is an adoption of it.

It is **not** the same measurement as this project's, and it is deliberately not
the headline metric here:

> BFCL scores the call. tooltrace-bench scores the run — recovery, side effects,
> cost, and whether a third party can reproduce the number.

Neither subsumes the other. An agent can emit every call perfectly and still
leave the workspace wrong; an agent can fumble a call and recover cleanly.
`tooltrace/tasks/packs/tool-call-structure/read-before-write.yaml` is the
demonstration: an agent that writes the correct answer without ever reading the
file scores **1.0 on the outcome assertion and fails overall**, because the
route it took was wrong. A benchmark inspecting only the end state would have
called that a pass.

## What this does not measure

- **Not correctness.** A structurally perfect call sequence can produce a wrong
  result. That is what the workspace scorers are for; a task should declare both.
- **Not semantics.** Argument *types* are checked, not whether a value is
  sensible. `{"path": "/etc/passwd"}` matches `{"path": "string"}`.
- **Nothing is executed.** These read the recorded request only, so they are as
  reproducible as the trace, and no faster or slower than reading it.
- **A trace is required.** A caller that supplies no trajectory gets an explicit
  refusal in the assertion detail, not a silent zero — "we could not look" and
  "we looked and it failed" are different facts.
