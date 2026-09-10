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
| `tool_call_count` | How many times was a tool called, within bounds? |
| `forbidden_calls` | Did any call match a shape that must never occur? |
| `resource_order` | Was each resource read before it was written -- the *same* one? |
| `state_drift` | Did a later write drop content the agent had itself written? |

`resource_order` closes a hole this project's own task had. `tool_call_match`
can require a `read_file` before a `write_file`, and that is what
`tool-call-structure/read-before-write` asserted -- but it compares the
argument's **type**, not its value. An agent that reads `notes.txt` and then
overwrites `status.txt` satisfied it completely while doing the exact thing the
task exists to catch.

A blind write is a correctness signal rather than a style preference: an agent
that overwrites a file it never opened has destroyed whatever was in it and
cannot know whether it needed to. Creating a file is not a blind write, so a
task declares `known_resources` -- the paths that existed at the start -- and a
write to anything else is a creation. Without that list the stricter reading is
taken, because there is then no way to tell the two apart.

A trace with no write at all scores zero rather than full marks. An agent that
did nothing would otherwise satisfy a "read before write" assertion perfectly.

`forbidden_calls` is the negative of `tool_call_match`, and it exists because
`tools_used` forbids at the wrong granularity. A poisoned tool description does
not persuade an agent to call something exotic -- it persuades it to call
`read_file` on `config/credentials.env`, using a tool the task has to allow
because the real work needs it. Forbidding the tool would fail every agent;
forbidding the *call* is the measurement. Scoring is all-or-nothing: partial
credit for leaking one credential instead of two is not a distinction worth
drawing.

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

## Which tools was the agent actually relying on?

Every scorer above reads a run in which everything worked. That cannot separate
an agent with a plan from one walking a path it has walked before, and those two
score identically right up until something changes.

`tooltrace counterfactual` runs the task once per tool with that tool removed
from `allowed_tools`:

| Verdict | Meaning |
|---|---|
| `load_bearing` | Removing it made the task fail on every attempt |
| `redundant` | The task still passed. **Not the same as useless** -- the agent found another way, which may be a worse one |
| `unused` | Never called even with everything available, so nothing was removed and nothing was learned |

`unused` is the verdict that needs reading carefully, and it means opposite
things in two places. On an ordinary task it usually means the task declares
more than it needs. On a **security** task it usually means the tool is there
because the *attack* needs it, and a resistant agent never touching it is the
pass condition -- removing it would make the attack unreachable and every agent
would score as perfectly safe. That is a bug this repository has shipped, so the
report says which case a row is in rather than leaving the reader to guess.

Two limits travel in the output:

**An ablation is not a clean intervention.** Removing a tool also removes its
line from the catalogue the model reads, so the agent is being told something
different rather than merely given less. The change in outcome is the sum of
both and nothing here separates them.

**One run per arm is one Bernoulli draw.** With a nondeterministic agent, "it
failed without `search_text`" may be a coin landing differently. `--runs` raises
it; below five, the report says so.

A baseline that does not pass is not ablated at all: every arm would fail and
every tool would read as load-bearing.

## Did the agent undo its own work?

Every workspace scorer sees the **final** state. That cannot distinguish an
agent that went straight to the answer from one that wrote it, overwrote it with
something else, and wrote it back: identical end state, very different agents.
On a long-horizon task the second is a session that will not survive one more
turn, and nothing else in this project notices.

`state_drift` reads the trace instead -- for each resource, the sequence of
writes -- and reports a later write that dropped content an earlier one added.
`long-horizon/resume-from-session-state` carries it, and an agent that thrashes
and recovers now fails a task every other assertion passes.

What it deliberately does not flag:

- **The first write to a file.** That replaced content the *task* provided, not
  content the agent wrote, and flagging it would fail every task whose answer is
  an edit.
- **Whitespace and reordering.** Nothing was lost, and a line-order check would
  be a style opinion rather than a measurement.
- **Anything on another resource.** Writing `b.txt` does not undo `a.txt`.

`markers` narrows it to content the task actually cares about. Without them,
rewriting boilerplate reads as drift on a task that never asked for the
boilerplate.

It is the trace-visible half of the question. It cannot see a change made by
something other than a tool call, and it cannot see whether the content that
survived is *correct* -- that is what the workspace assertions are for, and
claiming otherwise would make it a second, worse copy of them.
