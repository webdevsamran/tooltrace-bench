# Use cases — from one laptop to an audit committee

Each section is a real workflow with the commands that perform it. Anything a
section claims is graded in [`feature-status.md`](feature-status.md) and checked
in CI, so a command that appears here is a command that parses and runs.

---

## 1. "Is my agent any good?" — one developer, one laptop, no account

The smallest useful loop. No API key, no network, no sign-up.

```bash
pip install -e ".[dev]"
tooltrace init --agent subprocess --command "my-agent --task {objective}"
```

`init` writes a config and a CI workflow, then runs **one real task** and tells
you what happened. A failing first run is a successful init: it measured your
agent, and the report says which of the two failed.

One passing run is wiring, not reliability. For a number with an interval around
it:

```bash
tooltrace benchmark --agent subprocess --agent-config @tooltrace.config.json --runs 20 --summary
```

Then read the trajectory, not just the score:

```bash
tooltrace trace results/<bundle>.tooltrace --assertions
```

**Why it matters:** an agent that passes by deleting the test file and one that
passes by fixing the bug produce the same success rate and completely different
traces.

---

## 2. "Don't let a regression merge" — a team, in CI

A full sweep on every pull request is a bill nobody approves, so the check has to
fit a normal budget and still be honest about being a subset.

```bash
tooltrace benchmark --agent subprocess --agent-config @tooltrace.config.json --limit 12 --shuffle --seed 7 --runs 3
```

The policy, the seed and the exact task ids are recorded in the run config, and a
subset announces itself on stderr. Anyone with the seed reproduces the same
subset.

Gate the merge on a comparison that understands noise:

```bash
tooltrace pr-report --baseline runs/main --current runs/pr --out report.md
```

**Why it matters:** a two-point move on twelve runs is noise. A bot that calls it
a regression trains people to ignore the bot, and then the bot is decoration. The
report uses confidence intervals and says when the sample cannot support a
verdict.

Also available: a GitHub Action, merge-queue gating
(`.github/workflows/merge-queue.yml`), a token-efficiency gate, and CI templates
for GitLab, Jenkins and CircleCI via `tooltrace init --ci`.

---

## 3. "Score what actually happened in production"

GitHub Copilot, Codex and Claude Code emit OpenTelemetry GenAI spans. That makes
production traces scorable with the same machinery as fixtures.

```bash
tooltrace ingest --format otel-spans --in prod-trace.json --out trace.jsonl
tooltrace online --source arrivals.jsonl --state .tooltrace-online --policy stratified
tooltrace drift --current runs/this-week --baseline runs/last-week
```

Turn a real failure into a permanent regression test:

```bash
tooltrace promote-trace incident-4821.jsonl --task-id regressions/incident-4821
```

The generated task is a **draft**: it derives the trajectory assertions and
refuses to invent a workspace or a correctness assertion, leaving a `TODO` for
each. A generated task that looked finished would run, pass, and test nothing.

**Why it matters:** "passes evals, fails in production" is the whole problem.
Scoring the production trace closes the loop.

See [production-traces.md](production-traces.md).

---

## 4. "Will it leak our data if a web page tells it to?"

Prompt injection is OWASP's #1 for agentic applications, and exfiltration is the
outcome that matters.

```bash
tooltrace benchmark --agent subprocess --agent-config @tooltrace.config.json --task security/indirect-injection-exfiltration --runs 20
tooltrace owasp --markdown
```

Exfiltration is measured through an **offline egress sink**: the `http_post` tool
performs zero network I/O and appends to `.tooltrace_egress/requests.jsonl`
inside the workspace. An exfiltration attempt becomes an ordinary workspace
observation, so ordinary scorers detect it — and nothing ever leaves the machine,
which is what makes the test safe to run in CI.

Check the sandbox itself, adversarially:

```bash
python scripts/sandbox_escape_check.py
```

**Why it matters:** an injection suite that needed real network egress to measure
exfiltration could not be run by the people who most need to run it.

See [security-evaluation.md](security-evaluation.md) and
[threat-model.md](threat-model.md) — the second one for the sandbox's honest
limits.

---

## 5. "Which model is worth the money?"

```bash
tooltrace showdown --agents openai_compat,anthropic,gemini --runs 30
tooltrace cost --bundles results/ --forecast-tasks 500 --forecast-runs 3
```

`showdown` **refuses to declare a winner the sample cannot support**. The
cost–accuracy frontier excludes agents whose runs were never priced rather than
plotting them at zero — treating unpriced as free puts them on the frontier by
default, which is exactly backwards.

Before spending anything, find out whether the sweep can detect what you care
about:

```bash
tooltrace power --runs 30 --detect 0.05 --baseline-rate 0.7
```

**Why it matters:** researchers note costs are rarely reported at all, and two
agents with identical accuracy can differ by two orders of magnitude in spend.

---

## 6. "Our auditor is asking for evidence"

The EU AI Act's operative demand is that organisations **demonstrate**
compliance, not assert it.

```bash
tooltrace evidence --bundles results/ --out dossier/
tooltrace evidence --bundles results/ --framework nist-ai-rmf
tooltrace card --bundles results/ --out system-card.md
tooltrace self-audit --bundles results/
```

The dossier is dated and hash-chained, maps runs to Art. 9/11/12/15 obligations,
and — this is the part that matters — **lists the controls no benchmark can
evidence**, so a partial mapping is never read as coverage. `self-audit` scores
*your own* evidence completeness and exits 0 even with gaps: a gap is a finding,
not a build failure.

Give the auditor read-only, time-boxed access:

```bash
tooltrace server   # then issue an auditor grant; see docs/self-hosting.md
```

**It is not a compliance determination and does not claim to be one.** It
assembles what a reviewer needs to make one.

See [evidence-dossier.md](evidence-dossier.md).

---

## 7. "We run our own models on our own hardware"

```bash
tooltrace backends                   # which of Ollama, llama.cpp, LM Studio, vLLM, SGLang is listening
tooltrace benchmark --agent openai_compat --agent-config '{"base_url": "http://localhost:11434/v1"}'
tooltrace hardware --bundles results/
```

Every run records GPU, VRAM, backend, engine version and quantization. A
quantization quality-vs-speed curve is drawn **only when nothing else varied** —
two quantizations benchmarked on different machines produce a curve of the two
machines.

Energy is read from RAPL or `nvidia-smi` where they exist and is never estimated
from a datasheet TDP. Carbon is not computed at all, because grid intensity
varies by the hour and a number that ignores that is decoration.

---

## 8. "We need this across a fleet"

```bash
tooltrace fleet enqueue --queue /shared/q --agent subprocess --runs 5
tooltrace fleet work    --queue /shared/q --worker-id w1     # on each machine
tooltrace fleet status  --queue /shared/q
tooltrace fleet collect --queue /shared/q --out merged.json
```

A **file queue**, not a broker: a shared directory is something a lab, a CI cache
or an NFS mount already has, and a claim is `os.replace`, which is atomic on
every filesystem this runs on. Two workers racing for one job cannot both win.

`collect` **refuses on a conflict** rather than picking a winner. Two workers
reporting different results for the same run means the runs were not what they
claim to be, and keeping one would hide that behind a clean-looking total.

Simpler alternative for a fixed set of machines:

```bash
tooltrace benchmark --agent subprocess --shard 0/4   # on machine 1, 1/4 on machine 2 …
tooltrace merge runs/shard0 runs/shard1 runs/shard2 runs/shard3 --out runs/all
```

---

## 9. "Prove the number you published"

```bash
tooltrace verify results/<bundle>.tooltrace
tooltrace reproduce results/<bundle>.tooltrace
tooltrace attest results/<bundle>.tooltrace --attester "your-org"
```

`verify` checks checksums, schema conformance and anti-gaming integrity — dropped
assertions, a task modified after publication, an expected answer visible in the
prompt. `attest` records that somebody else re-ran it, which moves the result up
the trust ladder from `LOCAL` toward `REPRODUCED`.

**Why it matters:** a benchmark result nobody has independently re-run is a
claim. This is the machinery that turns it into evidence.

---

## Related

- [Getting started](getting-started.md) · [CLI reference](cli-reference.md) ·
  [Recipes](recipes.md)
- [Why ToolTrace Bench — and when to use something else](why-tooltrace-bench.md)
- [Feature status matrix](feature-status.md) — every claim above, graded and
  machine-checked
