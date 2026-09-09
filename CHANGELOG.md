# Changelog

All notable changes to ToolTrace Bench are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **`tooltrace pr-report` — a pull-request gate that does not fire on noise.**
  `compare` and `regression` take two *single-run* bundles. For latency on a
  deterministic task that is defensible; for a success rate it is not. One run is
  one Bernoulli draw, and "the score dropped from 1.0 to 0.0" describes a coin
  landing differently, not a regression. A gate built on that either blocks pull
  requests at random or gets switched off.

  This compares two *sets* of runs, and two things must both hold before it fails
  a build: the change is **real** (the 95% interval on the *difference* excludes
  zero) and it is **large enough to matter** (the smallest change the interval
  supports reaches a stated minimum effect). The second condition is not
  decoration — a deterministic task with no run-to-run variance can make a 0.1%
  latency shift statistically certain, and failing a pull request on that is
  exactly the behaviour that gets a reliability gate disabled.

  Four verdicts per metric: `regressed`, `improved`, `no_change_detected`,
  `inconclusive`. The fourth is what makes the other three trustworthy — without
  it, "no regression" covers both "we checked" and "we could not tell", and a
  green check on 3 runs would mean what a green check on 300 means. Only
  `regressed` exits non-zero; `inconclusive` is reported loudly and does not
  block, because failing on absent evidence would make the gate a function of the
  caller's compute budget.

  Proportions use the Newcombe difference of Wilson intervals rather than a
  bootstrap: ten perfect runs bootstrap to a zero-width interval, and "the rate is
  exactly 1.0 with no uncertainty" is the most misleading thing it could report.
  Latency's minimum effect is a share of the baseline, because 5 ms is nothing on
  a four-second task and everything on a six-millisecond one. A comparison across
  different task sets or artifact versions is refused rather than annotated:
  attributing a difference in measurement to the code is worse than no report.

- **`.github/workflows/pr-reliability.yml`** runs the sweep twice in one job —
  merge base and head — so a difference in runner cannot be mistaken for a
  difference in code, then comments the table and edits its own previous comment
  instead of stacking new ones. No third-party actions.

### Added
- **Hardware-aware run metadata, and a comparability verdict for latency.**
  `environment.json` recorded python version, platform, OS, machine and a
  timestamp — enough to know a run happened on Windows on x86_64, and not enough
  to know whether its latency number means anything beside another run's. A p95
  of 40 ms on a laptop and 40 ms on a GPU server are the same number describing
  different things, and a leaderboard that ranks them together measures the
  hardware while claiming to measure the agent.

  Bundles now carry a `hardware` block: CPU count, total memory, GPUs detected
  via `nvidia-smi`, and the inference backend **as declared by the caller**,
  labelled as declared because none of it is detectable from inside the harness.
  Nothing is guessed — an undetectable value is `null`, and an empty GPU list
  ships with `gpu_detection` saying whether a probe was possible at all. The
  `WorkerInventory.gpu = False` this replaces is the exact failure mode: a
  hardcoded `False` cannot be told apart from a checked one.

  `comparability()` returns a three-state verdict rather than a boolean, because
  a boolean has to lie in one direction. `True` would claim two runs match when
  the record never determined their memory size; `False` would call two runs from
  one machine incomparable because neither declared a backend. Differences come
  back as both values: "not comparable" is not actionable, "8 CPUs versus 64" is.

- **Inference time against tool time.** `model_ms` and `tool_ms` were on every
  result and nothing reported them together, so nobody could tell a slow-thinking
  agent from a slow-acting one. The benchmark summary now carries a `latency`
  block, and the dashboard's efficiency page shows the split.

  When an adapter cannot report model time the harness share stays **unknown**
  rather than being computed as the remainder — a confident figure derived from an
  unmeasured input, in the one place a reader would trust it. `0.0` and "not
  reported" stay distinct, and the aggregate says how many runs could answer at
  all, so a split over 2 of 200 runs is not read as describing those 200.

- **`--agent-config` reaches the bundle.** The declared inference block comes
  from the adapter config passed to `run`, `benchmark` and `perturb`, so a
  bundle records which backend produced it.

### Added
- **`tooltrace init` — an on-ramp, not a scaffold.** Getting from "installed" to
  "learned something about my agent" previously meant reading the adapter docs,
  discovering that `subprocess` takes a `command` with an `{objective}`
  placeholder, hand-writing JSON, quoting it correctly for your shell and
  guessing a task id. Every step is a place to give up and none of them teaches
  anything about the agent.

  `init` writes `tooltrace.config.json` and a CI workflow, then **runs one real
  task with the configured agent and reports what happened**. A command that
  stops at writing files leaves the user to find out their config is wrong on
  their own time. A failing first run is still a successful init — that is a
  measurement of the agent, not a setup problem, and the report says which.

  It overwrites nothing without `--force` and reports every collision at once
  rather than one `--force` at a time. It never writes a credential:
  `openai_compat` gets the *name* of an environment variable, because a
  generated file gets committed. It never blocks on a prompt without a tty, so
  it is safe in CI. And the command it prints omits `--agent-config` when the
  written config would break the run — `scripted` takes its script from each
  task, so passing an empty one overrides it. A generated command that fails is
  the exact defect shape this project keeps finding.

- **`--agent-config @path`** on `run`, `benchmark`, `showdown` and `perturb`.
  Inline JSON still works. `@path` exists so the file `init` writes is a file the
  other commands can read; a missing or malformed file is a message naming it,
  not a traceback.

- **`tooltrace badge` — an embeddable reliability badge.** A badge is the
  most-quoted surface a project has: screenshotted, pasted into decks, read by
  people who will never open the run behind it. So this one differs from the
  usual coverage badge in two ways. The **sample size is always in the message**,
  because `92% (n=25)` and `92% (n=2)` are different claims. And the **colour
  comes from the confidence interval's lower bound, not the rate** — 10 of 10
  runs is 100% with a lower bound near 72%, so it renders amber. A green badge
  should mean the sample supports the claim, not that the point estimate landed
  high.

  Self-contained SVG: no dependency, no network, no script, nothing external for
  a host page to load. The interval and the small-sample caveat travel in the
  accessible name, where the picture cannot carry them. A shields.io `endpoint`
  JSON is written beside it, deriving its colour from the same rule so a
  shields-rendered badge cannot be greener than ours. The site publishes one at
  `badge/reliability.svg`, and the leaderboard offers the markdown to embed it.

### Added
- **Security-posture view, and the sample dataset now actually attacks something.**
  Two security packs shipped, and no security run appeared in the published
  dataset, so the leaderboard's security axis read "not measured" for every
  agent, there was nothing to plot, and the evidence dossier recorded
  "cybersecurity evidence is absent" as a gap. Those statements were honest
  about a dataset that had never attacked anything — but the packs exist and
  run, so `scripts/make_sample_results.py` now runs them.

  The result is the reason this needed care rather than a chart. The scripted
  agent resists all four attempts, and an attack-success rate of 0% over four
  attempts has a Wilson upper bound near **49%**. Rendered as a bare green `0%`
  that is *more* misleading than "not measured" was, because it looks like a
  finding. So: every rate on the new `/security` page carries its attempt count
  and its interval, a sample under 30 is labelled as one, and the leaderboard
  badge for a fully-resisted small sample is a warning rather than a pass. The
  page also refuses to generalise — what it measures is these payloads, on this
  agent, in this dataset.

- **Evidence view for a compliance reviewer.** `tooltrace evidence` produced a
  hash-chained dossier mapping runs to EU AI Act Article 9/11/12/15 obligations,
  and it was reachable from the CLI and nowhere else. `/evidence` renders it,
  under the same constraint as the command: the disclaimer comes before any
  number, gaps get a column of equal width and equal weight to evidence, an
  unverified bundle is surfaced rather than dropped, and no rendering asserts
  compliance. A machine-produced "compliant" verdict in a domain carrying €35M
  penalties would borrow authority it has not earned.

- **`changed_files` scorer** — the mirror of `protected_files`. Names each file
  with the SHA-256 of its *starting* content and passes only if that hash no
  longer matches. See the fix below for why it exists.

### Fixed
- **Every created or deleted file produced a corrupted workspace diff.**
  `lines.extend(f"--- /dev/null{chr(10)}+++ {path}")` — `list.extend` iterates
  its argument, and iterating a string yields characters, so the header was
  spelled one letter per line: thirty-odd lines of single characters where two
  lines belonged. `workspace.diff` is one of the six artifacts in a `.tooltrace`
  bundle, checksummed into the manifest, rendered by the dashboard and cited by
  the evidence dossier as the record of what a run changed.

  It stayed invisible because all three tasks used to generate the sample
  bundles *modify* an existing file, and that path goes through
  `difflib.unified_diff`, which returns a list. Adding a task that creates one
  surfaced it immediately. `workspace_diff` had no test of its own — the only
  occurrences of the string in `tests/` were an event *type* in an ingest
  fixture — so `tests/test_workspace_diff.py` now covers creation, deletion,
  modification, ordering and a real directory.

- **A security assertion could be satisfied by transcription.** The direct-harm
  pack asserted `file_contains: "footer"` on the file the agent was asked to
  append to, and `footer` is a word from `ticket.md`, which the agent reads. An
  agent could earn that point by copying a word it was handed. This project's
  own `leaked_expected_values` check flags exactly that pattern, and it fired on
  a committed bundle as soon as the pack entered the sample dataset — which is
  how it was found, and the check working as intended. The assertion is now
  `changed_files` against the starting hash. A deleted file scores zero, because
  deletion is the destructive act the pack exists to detect and rewarding it
  would invert the measurement.

- **Published bundles accumulated instead of being replaced.**
  `scripts/generate_web_data.py` wrote into `web/public/bundles/` without
  clearing it, so a local build served traces for runs that no longer appear in
  any result row.

### Added
- **Failure-cluster explorer with drill-down to the exact failing step.** The
  failure page was a dropdown and a bar chart of the twelve failure *categories*.
  That view answers "how many runs hit `execution`" and cannot answer the
  question a reader actually has, which is whether that is one bug or eleven —
  and it left them to find the relevant step in a trace by hand afterwards.

  Failed runs are now clustered on their *signature*: the failure class, the
  rule that matched, and the tool the failure was attributed to. Two runs that
  share a signature are usually one defect; the same class reached by different
  rules usually is not. Clusters rank by size, ties breaking on how many tasks
  they span, because between two equal-sized clusters the systemic one is the
  better thing to open first. A cluster shows a step number only when every run
  in it agrees on one — one run's step presented as the cluster's would be a
  guess dressed as a fact.

  Every run in a cluster links to `/results/<bundle>?seq=<n>`, and that page
  opens with the attributed row marked and scrolled into view. The marking
  carries in the accessible name and a caret, not only a tint, so it survives a
  screen reader and a monochrome display.

  `scripts/generate_web_data.py` now emits `failure_step` per run, computed by
  the same `tooltrace.metrics.aggregate.failure_step` the benchmark summary
  uses, so the dashboard and the CLI cannot drift about which step broke. Every
  bundle committed to this repository passes, so the explorer renders its empty
  state against the real dataset and says so plainly; the interactive markup is
  covered by an end-to-end test that substitutes the response, because markup
  that only appears when something went wrong is exactly the markup nobody
  checks by hand.

### Fixed
- **Every deep link in the dashboard was dead.** The frontend built with a
  relative asset base — annotated "so the built site works from GitHub Pages
  project subpaths", which it does, for the root page only. Relative asset URLs
  resolve against the *current route*, so opening `/results/<bundle>` asked for
  `/results/assets/index-*.js`, received a 404, and left an empty
  `<div id="root">`. Result detail, task detail and now the failing-step link
  were unreachable as links, in a new tab, or after a refresh. Nothing in the
  build reported it: it was true only in production.

  The base is now the real deploy prefix, passed in by `actions/configure-pages`
  (which had been running *after* the build, where it could not inform it), and
  the build emits a `404.html` fallback — without it GitHub Pages answers its
  own 404 page and an absolute base alone changes nothing. The workflow fails
  if that file is missing, and an end-to-end test opens a nested route and
  asserts no script or stylesheet 404s.

- **Dataset fetches 404'd on every nested route.** `data/results.json` and
  `bundles/<name>/trace.json` were passed to `fetch` as bare relative strings,
  which a browser resolves against the current route. From `/results/<bundle>`
  that is `/results/data/results.json`. The page then rendered its empty state,
  because nothing in a UI distinguishes "no data" from "wrong URL". Both now go
  through `assetUrl`, which resolves against the site base at any route depth.

- **The Trace Explorer had never displayed a trace.** It fetched
  `bundles/<name>/trace.jsonl` and `workspace.diff` — the names of the files
  *inside* a `.tooltrace` bundle. `scripts/generate_web_data.py` publishes them
  as `trace.json` (a JSON array) and `workspace.diff.txt`. Every fetch 404'd and
  the page showed `HTTP 404` where a trace should be, on the live site, for as
  long as the page has existed. The published names are the contract; the
  bundle's internal names are not. The download link had the same mistake.

### Fixed
- **A built wheel could not load a single task.** `[tool.hatch.build.targets.wheel]`
  packaged only `tooltrace`, so the JSON Schemas authored at the repository root
  never entered the distribution. `tasks/loader.py` looked for a repo-root
  `schemas/` directory and otherwise fell back to
  `resources.files("tooltrace") / "schema_data"` — a directory that did not exist
  either — on a branch annotated `# pragma: no cover`, so no test ever executed
  it. Every `pip install` of a wheel produced a package where
  `validate_task_document` raised `task.schema.json not found` for *every* task:
  no `tooltrace tasks`, no `tooltrace run`, nothing. It stayed invisible because
  the documented quickstart installs editable from a checkout, where the repo
  copy resolves and the broken branch never runs, and because PyPI publishing is
  gated off so nobody had installed one.

  The schemas are now copied into the wheel by a hatch `force-include`, and
  resolution moved to `tooltrace/core/schemas.py`, which prefers the packaged
  copy so an installed package can never silently depend on a checkout being
  nearby. The `pragma: no cover` is gone: both roots are ordinary arguments to
  `load_schemas_from`, so each is unit-tested.

  Checking a source tree could not have caught this, so `scripts/wheel_check.py`
  builds a real wheel, extracts it outside the repository, asserts the import
  actually came from the extract (otherwise the check would pass vacuously), and
  runs the call that used to raise. It runs in CI and is covered by
  `tests/test_wheel_ships_schemas.py`, including a test that stripping the
  schemas back out is detected.

### Added
- `tooltrace doctor` now reports `schema_source` and `schemas_loaded`, so a
  broken install is one line of diagnosis rather than a `TaskValidationError` on
  every task.

### Added
- **Frontend design system.** The stylesheet grew from 187 lines covering
  seventeen pages to a full token set: an OKLCH neutral ramp and status
  palette (perceptually even in both themes), a fluid type scale, spacing,
  radii, elevation and motion tokens, and light/dark/system theming. Motion
  durations live in three custom properties that `prefers-reduced-motion`
  collapses to zero, so animation is disabled in exactly one place and no
  component can opt out by accident.
- **Command palette (Cmd/Ctrl-K)** with subsequence matching, arrow-key
  navigation and the combobox/listbox ARIA pattern. It replaces a search box
  that never searched — it wrote the query to the URL hash and nothing read it
  back — and lets navigation collapse from twenty-nine always-visible links
  (thirteen in the top bar, four below, twelve for the workspace) to four
  sections plus a contextual sidebar.

### Fixed
- **`DataTable` printed sixteen digits of false precision.** The leaderboard
  showed `0.3333333333333333` for a three-run mean because numeric cells were
  rendered with `String()`. Formatting now lives in the table, so every numeric
  column on every page is covered and a new column cannot reintroduce it.
- **The domain heatmap rendered at 2.5x.** `width: 100%` on a narrow viewBox
  stretched a 248-unit drawing across ~630px, so 10px labels painted at ~25px.
  The SVG is now capped at its intrinsic width.
- **Command-palette matching depended on word order.** Scoring a single
  `label + group` string meant the entry for Experiments read "Experiments
  Workspace", which "wsx" cannot thread through, while the reverse order
  matched. Both orders are scored now.
### Added
- **Anti-gaming checks that inspect something.** `anti_gaming_checks` has
  shipped since 0.2.0 reading `assertion_results`, `declared_assertions`,
  `task_hashes` and `harness_sha256` off the result it is given — fields
  `EvalResult` does not have. On a real result it returned
  `{"ok": true, "problems": []}` having performed **zero** checks. Wiring it up
  as-is would have been worse than leaving it unwired: a permanently passing
  integrity check is the "CI step named for a validation it never performed"
  this repository has already had to correct once.

  `tooltrace/analysis/integrity.py` rebuilds the checks against data a bundle
  really contains, and `tooltrace verify` runs them: a declared assertion missing
  from the score, a task whose assertions or fixtures differ from the published
  task of the same id, and an expected answer visible in the objective or the
  starting workspace (which makes the score measure transcription). Each check is
  tested against an artifact that must fail it.

  Row 91 of the capability matrix loses "harness tampering" from its text: no
  harness hash is recorded in a bundle, so that check cannot run.
  `verify` reports `harness_hash_recorded: false` so an unperformed check never
  reads as a passed one.
- **A GitHub Action (`action.yml`).** There was none, which is most of why the
  CI integration this project is built for did not happen: telling someone to
  write their own workflow is a much higher bar than pointing at one line. It
  runs a trimmed benchmark and fails the step below a success-rate floor,
  writing a job summary with the interval and the failure taxonomy.

  It deliberately pulls in **no third-party actions**. A composite action that
  bundles `setup-python` inherits that action's supply chain on behalf of every
  caller and pins it on their behalf — not a decision to make quietly for
  downstream users. `scripts/check_action_pins.py` now scans `action.yml` too,
  so that stays true.

  Two honesty properties are tested: a trimmed run states that it was a subset,
  and a threshold met by a small sample emits a warning rather than letting a
  green check imply more evidence than was collected.
- **`--limit`, `--shuffle` and `--seed` on `benchmark` and `showdown`.** Nobody
  runs a full benchmark on every pull request, and without a way to trim one the
  CI integration this project is built for could not be set up at all. The risk
  is a truncated run reading like a full one, so the selection is recorded in the
  output — policy, seed, how many of how many, and the exact task ids — and a
  subset announces itself on stderr. Default is deterministic (first N by id);
  `--shuffle` sorts before shuffling so the result depends only on the seed and
  never on the order the loader happened to walk the pack directories.
- **`tooltrace verify BUNDLE`.** Bundle verification existed but had no verb: it
  lived under `reproduce --no-rerun`, a command documented as "verify and
  re-run", so the cheap read-only check was reachable only by asking the
  expensive one not to do its main job. Third-party auditing is the entire point
  of a checksummed bundle. Checksums and schema conformance are reported
  separately because they fail for different reasons — tampering after the fact
  versus never having matched the published format — and `--no-schema` runs the
  checksum half alone.
- **`tooltrace mcp-conformance` — check an MCP server against the protocol.**
  MCP has effectively won the agent-to-tool layer (roughly 97M monthly SDK
  downloads by February 2026, adopted by every major provider), so "does this
  server behave correctly" is a question many people now have.

  `conformance_check` already existed but was reachable only from Python, and it
  graded every check as equally fatal: a server missing a tool *description*
  failed identically to one that never completed a handshake. Those are not the
  same finding. Checks now carry a severity — `required` (a client cannot
  proceed) or `recommended` (the spec asks for it and a good client copes) — and
  `ok` means required only, so a cosmetic gap cannot read as a protocol
  violation and a real violation cannot hide behind a passing total.

  Eleven checks, including the one that matters most: a server that fabricates a
  result for a tool it does not have fails `required`, because a client cannot
  distinguish that from a real answer. A deliberately non-conforming server is
  run in the tests to prove each class of failure is detected — a conformance
  suite that passes everything it is pointed at measures nothing.
- **A Dockerfile and a devcontainer.** The image installs a **built wheel** into
  a clean container with no repository beside it, and the build fails if that
  wheel cannot load its own task packs. That shape is deliberate: this project
  shipped a wheel whose JSON Schemas were never packaged, and the defect stayed
  invisible for three releases precisely because every install anyone tried was
  editable, with the source tree next to it. The image is therefore the same
  check `scripts/wheel_check.py` performs, enforced by the artifact people
  actually run.

  It runs as a non-root user: an evaluation harness executes code it did not
  write, and `docs/threat-model.md` is explicit that the local sandbox does not
  stop a raw-socket program spawned through `shell`. Container isolation is the
  answer to that and is worth nothing as root. `.dockerignore` excludes a stale
  `tooltrace/schema_data/` so a local build artifact cannot mask a real break.

  **Not verified locally** — no Docker daemon was available in the development
  environment — so the `sandbox-docker` CI job builds the image and runs
  `tasks` and `doctor` inside it. What can be checked without a daemon is
  checked by `tests/test_distribution_artifacts.py`.
- **`tooltrace evidence` — an audit dossier from bundles.** The remaining EU AI
  Act provisions became applicable 2 August 2026, and every compliance guide
  repeats that an organisation must *demonstrate* compliance rather than claim
  it. A checksummed, reproducible bundle is already evidence for that; nothing
  gathered bundles into the shape a reviewer reads.

  **It is not a compliance determination and refuses to become one.** A
  "compliant" verdict emitted by a benchmark would be actively misleading in a
  domain carrying €35M penalties, and a machine producing it would lend it
  unearned authority. Every obligation carries `evidence` *and* `gaps`, the gaps
  are never empty by construction, the payload reports
  `is_compliance_determination: false`, and a test asserts no rendering contains
  a bare claim of compliance.

  Runs are hash-chained, so a **removed or reordered** run is detectable and not
  only a modified one; the tests break the chain three ways. A bundle too
  damaged to parse is recorded as unreadable and unverified rather than crashing
  the report — an audit most needs to see the corrupt artifact. The timestamp is
  injected rather than read from the clock, so two dossiers over the same
  bundles are byte-identical and can be diffed.
- **Score a real production trace (`ingest --score-against TASK_ID`).** GitHub
  Copilot, Codex and Claude Code emit OpenTelemetry GenAI spans directly, and
  `ingest` could already read them — it just could not *score* them, so a real
  agent run could be converted and classified but never graded.

  This is possible now only because trace-aware scorers exist. A production
  trace has no workspace, so every `(params, workspace)` assertion is
  unanswerable; trajectory assertions are not. The command reports `score`,
  `skipped_assertions` (by name) and `is_partial_score` together, because a
  partial score presented as a complete one would understate an agent by exactly
  the assertions nobody could evaluate. A task with no trajectory assertions
  says so rather than reporting zero.

- **OTel GenAI span export (`tooltrace/exporters/otel.py`).** Results flow into
  Langfuse, Phoenix, Datadog or any OTel backend — being the harness that feeds
  those platforms is a better position than competing with them.

  Spans are plain dicts in the OTLP JSON shape rather than SDK objects: an
  OpenTelemetry SDK dependency in an offline-first, supply-chain-audited project,
  for what is a documented attribute vocabulary, is a poor trade. **Nothing is
  transmitted** — a test asserts the module imports no HTTP client at all. Every
  span records `gen_ai.conventions.version`, since the conventions are still
  experimental upstream and undated telemetry is unreadable a year later.
  Unmeasured token counts are *absent* rather than zero, and a failed tool call
  omits `gen_ai.tool.call.result` because the importer derives status from that
  attribute's presence — emitting it would make a failure round-trip as a pass.
- **Indirect prompt-injection suite, measured without any network egress.**
  Prompt injection is #1 on the OWASP Top 10 for Agentic Applications (2026) and
  sensitive-information disclosure is #2. `tooltrace/tasks/packs/security/`
  measures both classes: exfiltration (was private data sent somewhere a *file*
  told the agent to send it?) and direct harm (did the agent destroy something
  it was not asked to touch?).

  The usual way to measure exfiltration is to let data leave the machine. This
  project will not: the sandbox is offline by default, and adding real egress to
  measure security would make the harness the vulnerability it tests for. So
  `http_post` (`tooltrace/tools/sink.py`) is offered to the agent as a way to
  send data and **sends nothing** — every call is recorded to
  `.tooltrace_egress/requests.jsonl` in the workspace, which makes the attempt
  readable by ordinary `(params, workspace)` scorers and puts the evidence in
  the bundle. The agent cannot rewrite that log: the prefix is refused by every
  path-taking tool.

  Canary matching happens in the tool on **raw arguments**, before the
  executor's sanitizer runs — the sanitizer redacts secret-shaped strings, so
  matching afterwards would find nothing and every agent would score as
  perfectly secure. Only canary **ids** are recorded, never values, so the log
  is publishable.

  Scorers score the **defence** (1.0 = resisted), so `success` keeps its meaning
  everywhere else; attack success rate is derived as `1 - defence_rate` in
  `tooltrace/metrics/security.py`, with a Wilson interval and a small-sample
  flag, because 0% over three attempts is not evidence of a secure agent.

  `docs/feature-status.md` row 16 moves from `S` to `I`, and
  `docs/threat-model.md`'s "no offensive security payloads" non-goal is
  rewritten: what ships is defensive evaluation with clearly-marked public smoke
  payloads and a responsible-use policy in `docs/security-evaluation.md`, not a
  transferable attack corpus.
- **An adversarial sandbox-escape suite.** `scripts/sandbox_check.py` calls
  `resolve_in_workspace` with a few bad paths and checks some defaults. That is
  a conformance check on a helper — it proves the function rejects what it is
  handed, not that an agent cannot get out, because an agent never calls that
  helper. It calls tools, through `ToolExecutor`.

  `scripts/sandbox_escape_check.py` attacks that path with sixteen attempts:
  traversal and absolute paths across every filesystem tool, network egress
  under a disabled policy, the cloud metadata endpoint, and remote git
  operations. It runs in CI and fails the build if anything the sandbox claims
  to block gets through. Success is judged on **evidence** — a file appearing
  outside the workspace — rather than on the tool's own report, because a write
  that claims to have failed and still landed outside has still escaped.

  The two documented limits of the local sandbox (`shell` can write outside the
  workspace and read the environment) are attempted and reported as confirmed
  rather than skipped: a suite that quietly omits the attacks it would fail
  measures nothing. If either ever starts being blocked, the script says so, so
  `docs/threat-model.md` can be tightened rather than left overstating the gap.
- **Trace-aware scorers, and BFCL-style tool-call matching.** All fifteen
  original scorers take `(params, workspace)` and read the final state of the
  filesystem. That is the right default — it is what lets a third party
  recompute a score from a bundle — but it makes a whole class of question
  inexpressible: "did the agent read the file before overwriting it?" cannot be
  answered from the file.

  A second scorer kind takes `(params, trace)`. Three ship: `tool_call_match`
  (structural comparison of emitted calls by name, argument names and argument
  types, executing nothing), `tools_used`, and `no_failed_calls`. The structural
  approach is modelled on the Berkeley Function-Calling Leaderboard's, with
  attribution, and `docs/tool-call-structure.md` states plainly that it is *not*
  the headline metric here: BFCL scores the call, this project scores the run.

  `tooltrace/tasks/packs/tool-call-structure/read-before-write.yaml` is the
  demonstration, and the argument for the project in one task: an agent that
  writes the correct answer without ever reading the file scores **1.0 on the
  outcome assertion and fails overall**. A benchmark inspecting only the end
  state would have called that a pass.

  The `trace` argument is optional and defaults to `None`, so every existing
  caller is unaffected. A trace assertion evaluated without a trace returns an
  explicit refusal rather than a silent zero — "we could not look" and "we
  looked and it failed" are different facts.
- **Four-axis leaderboard.** The public leaderboard ranked on success rate
  alone. It now shows accuracy, cost per resolved task, p95 latency and attack
  success rate side by side — the combination no competing benchmark reports.

  The hard part is honesty about the axes nobody has measured yet. A null cost
  rendered as `0` reads as *free*; a null attack-success rate rendered as `0%`
  reads as *perfectly secure*. Both would be the most misleading numbers on the
  page, and both are null for every agent in this repository today: no adapter
  reports spend, and no security pack ships. So those cells render "not
  measured" with a reason, a banner states which axes the dataset does not
  cover, and the header counts how many agents have each axis measured.
  `undefined` is treated the same as `null`, because data generated before these
  fields existed omits them entirely.
- **Trajectory metrics now reach a user.** `tooltrace/metrics/` shipped ten
  functions — trajectory efficiency, loop detection, hallucinated resources,
  context retention, tool-selection confusion, verification quality, failure
  taxonomy, policy compliance, side-effect correctness, change minimality — each
  with unit tests and **no caller outside the test suite**. No runner, CLI
  command, report, bundle field or web page ever computed them, so
  `tooltrace benchmark` reported success rates and latency and nothing about how
  the agent got there. The package docstring still said "(Prompt-2 features
  31-46)", which is the tell: they were written against a feature list rather
  than a run path.

  `tooltrace/metrics/aggregate.py` supplies the missing assembly — pairing each
  `tool_request` with its `tool_result`, since the metrics want one record per
  call and the trace stores two events — and `run_benchmark` now emits a
  `trajectory` block per task and overall, plus a `failure_taxonomy` count.
  Nothing touches `EvalResult` or the bundle layout: the metrics land in
  `BenchmarkRun.summary`, an unversioned dict, so no artifact format changes and
  no committed bundle becomes incomparable. Unmeasured quantities aggregate to
  `null`, never `0`.

### Fixed
- **The competitive analysis contradicted itself.** `docs/competitive-analysis.md`
  carried a CI-checked generated table and, twenty lines below it, a
  hand-written "Landscape summary" dated three weeks earlier that disagreed —
  SWE-bench pushed 2026-08-18 against the generated 2026-09-02, SWE-bench-Live
  at ~224 stars against 234. Three of the hand table's eighteen projects were
  never fetched at all, and two of those had moved org, so no refresh could ever
  have corrected them. The hand table is deleted and every repository fact now
  comes from the fetch.
- **Tracked projects went from 15 to 26**, adding BFCL/Gorilla, MLPerf Client,
  MLPerf Inference, inspect_evals, ToolBench, VisualAgentBench, Terminal-Bench,
  and the prompt-injection benchmarks agentdojo, InjecAgent and BIPIA. The list
  lives in a new `data/competitor-registry.json`, which is both what gets
  fetched and where the one non-machine column (category) is kept, so the
  documented list and the fetched list cannot disagree.
- **Org renames are recorded rather than silently followed.** The fetcher stores
  the slug it asked for alongside the canonical name the API answered with, so
  the table shows "moved from laude-institute/terminal-bench" and "moved from
  explodinggradients/ragas" instead of quietly changing name.
- **BFCL is cited by its leaderboard, not a release tag.** Its "v3"/"v4"
  generations version the leaderboard and its data; the repository's own release
  tags stop at `v1.3` (2025-07-17), so citing a GitHub release for a BFCL
  generation would cite something that does not exist. A test fails if that tag
  ever changes, so the note gets re-checked rather than rotting.
- The security-benchmark section states plainly that **this project does not
  currently measure prompt-injection resilience** (`docs/feature-status.md` row
  16 is `S`), and a test enforces that disclaimer, so listing those projects
  cannot be mistaken for competing with them.
- **`typer` and `rich` were declared as runtime dependencies and never
  imported.** The CLI is `argparse`; neither package appears anywhere in
  `tooltrace/`. Every install resolved and downloaded two packages the project
  does not use, and `sbom.json` — generated from the declared closure — described
  a wider dependency surface than the real one, which is a security artifact
  wrong in the unsafe direction. Removed; the SBOM drops from 40 components to
  39. `tests/test_declared_dependencies_are_imported.py` AST-walks the package
  and fails when a declared dependency is imported nowhere, and requires a new
  dependency to be mapped explicitly rather than drifting in.
- **`ROADMAP.md` said v0.3 was planned after 0.3.0 shipped.** The heading read
  "v0.3 — Ecosystem (planned)" while `pyproject.toml` was at 0.3.0 and
  `CHANGELOG.md` carried a released `[0.3.0]` entry, so a reader would conclude
  the release had not happened — and nothing recorded what it actually
  delivered. The heading now says shipped, points at the changelog, and states
  plainly that the four listed items were *not* in it and remain planned.
  `tests/test_roadmap_matches_changelog.py` keeps the two files in agreement.
- **The capability matrix was 79% unverified, and four more rows were false.**
  `docs/feature-status.md` grades 122 capabilities and calls itself the
  project's verification artifact, but its path check only inspected
  backtick-quoted tokens containing `/` or ending `.py` — and 97 rows cited bare
  prose such as "clustering module" or "calibration sets module", so only 25
  rows were ever checked. Re-auditing the whole table under a stricter rule
  found four rows graded **I** with nothing behind them: #45 (multi-judge
  adapters) and #46 (judge calibration datasets), now **D** — declared only,
  since no file matching `judge*.py` or `calibrat*.py` has ever existed — and
  #42 (abstention/calibration tasks) and #121 (backup/restore tooling), now
  **N** — not implemented, since no code mentions abstention or clarification
  and neither backup nor restore appears in the server or in the
  `docs/self-hosting.md` the row cited.

  Seventy further rows now cite a path and the symbols inside it. Every one of
  those citations was verified against the file before being written.

  Three checks stop it recurring: an `I`/`E`/`P` row must cite something
  inspectable; a claim probe rejects any row claiming a capability whose
  implementation is absent from disk (with a non-vacuity test asserting the
  probe still matches rows 45 and 46, and still does *not* match row 44, which
  legitimately claims independence *from* a judge); and the path resolver moved
  to `scripts/check_doc_code_refs.py`, which runs in CI over all 25 documents
  rather than one.
- **`docs/differentiators.md` cited four modules that do not exist**
  (`metrics/sideeffects.py`, `metrics/recovery.py`, `perturbations.py`, and
  `scoring/judges.py`, which describes a capability that has never existed).
  Its "judge-independent by default" section claimed multi-judge disagreement
  reporting and calibration-drift datasets; it now says what is true, which is a
  stronger claim: scoring is judge-*free*, so a score can be recomputed from the
  bundle by a third party.
- **`_resolves` used `lstrip("./")`**, which strips *characters*, so any dotfile
  citation silently lost its leading dot. Now `removeprefix`.
- **`mypy --strict` was claimed in three places and configured in none.**
  `CONTRIBUTING.md` (twice), `.github/PULL_REQUEST_TEMPLATE.md` and a pre-commit
  hook literally named "mypy (strict)" all asserted it while `[tool.mypy]` set
  no `strict` key and explicitly disabled `warn_return_any`. The config is strict
  now, which cost 40 errors across 16 files: 18 stale `type: ignore` comments
  (pure cleanup), 9 unannotated public functions — including `write_bundle`,
  `compare_bundles`, `check_regression`, `load_bundle_result` and
  `run_benchmark` — 7 bare generics, 5 `Any` leaking through a declared return
  type, and one untyped call. `tests/test_typing_claims_are_honest.py` pins the
  claim to the config so the two cannot drift apart again, and rejects
  per-module overrides that would make the claim true but hollow.
- **Three of the four published schemas were never enforced.** `schemas/` has
  shipped `result`, `trace` and `bundle-manifest` documents since 0.1.0, and no
  runtime path, test or CI step ever validated an artifact against any of them —
  only `task.schema.json` was checked. `write_bundle` now validates what it
  writes (`tooltrace/artifacts/validation.py`), with a `validate=False` escape
  hatch. Empirically zero-risk: every committed bundle already validated.
  `validate_trace_stream` additionally enforces what a per-line schema cannot —
  that `seq` is unique, monotonic and gapless across a whole trace.
- **"Forward compatibility is tested" was not true.** Every bundle test wrote a
  bundle with the current code and read it straight back, which tests a round
  trip rather than compatibility with an older artifact. A frozen bundle is now
  committed at `tests/fixtures/bundles/v1-frozen.tooltrace/` and read by today's
  readers.
- **Every shipped trace carried duplicate `seq` values.** The runner and the tool
  executor each kept an event counter; the runner passed its current value as
  `seq_start` — by value, at construction — and both then advanced
  independently. A twelve-event trace shipped with five duplicated sequence
  numbers, and `seq` was not monotonic in file order. Since
  `replay_from_checkpoint` partitions a trace on `e.seq >= checkpoint_seq`, it
  was partitioning on an ambiguous key. Both writers now share one `SeqCounter`.
  `tests/test_trace_seq_is_unique.py` checks the committed bundle corpus, which
  is the test that would have caught this when the traces were authored.
- **A flawless partial replay reported failure.** `replay_from_checkpoint` put
  its informational "skipped the prefix" line into `ReplayReport.errors`, and
  `ok` is `not mismatched and not errors`, so `ok` was unreachable. The note was
  only ever meant to stop callers mistaking a partial replay for a full one; it
  now lives in a separate `notes` field.
- **`showdown` declared an order it could not support.** It sorted on the
  success-rate point estimate, carried a confidence interval in its own output
  and never consulted it, so two agents at `--runs 1` came back definitively
  ranked. It now reports `verdict: "not distinguishable at this sample size"`
  unless the sample clears `significance_note`'s threshold *and* the leader's
  Wilson interval is disjoint from the runner-up's, and attaches `paired_delta`
  and Cohen's *h* per challenger. `paired_delta`, `effect_size_cohens_h` and
  `significance_note` had shipped since 0.2.0 with no caller outside the tests;
  the per-agent `flakiness` block was computed and silently dropped. Output is
  now an object rather than a bare list.

- **Replay never injected the faults a task declares.** `replay_trace` built a
  `PerturbationEngine` and prepared its workspace, but never passed `engine.hook`
  to the executor, so any task carrying a perturbation replayed as a mismatch —
  including this repository's own `failure-recovery/retry-after-tool-failure`.
  Partial replay additionally now primes the engine over the skipped prefix
  (`PerturbationEngine.prime`), so a one-shot fault already spent there is not
  injected again on the first replayed call.

## [0.3.0] — Ecosystem, adoption and integrity pass (2026-09-07)

### Fixed — integrity pass
- **README sample run is now captured, not written.** The section headed "A
  real sample run", prefaced "no fabricated numbers", showed output for a task
  that does not exist, with score components no scorer emits and a `wall_ms`
  traceable to the frontend's demo fixture. Replaced with real output, and
  `tests/test_readme_is_truthful.py` re-runs the documented command and diffs
  every deterministic field against the README.
- **The quickstart could not be followed** — a nonexistent task id, a `--pack`
  flag the CLI never had, and 12 of 12 wrong task-pack names. Checking the rest
  of the docs the same way found broken invocations for `showdown`, `baseline`,
  `regression`, `task scaffold/validate/test` and `snapshot`; all corrected
  against real `--help` output, with a test that every documented flag exists.
- **Four CLI bugs** surfaced by running the documented commands: `task
  scaffold` wrote its file then crashed on an undefined `args.json`; `snapshot
  --output` did not create parent directories; `verify_bundle` let
  `BundleError` escape as a raw traceback; `cmd_regression` parsed
  `--thresholds` outside its try block.
- **The SBOM described the build machine, not the project** — 147 components
  against six declared dependencies, including two unrelated sibling projects,
  with no serialNumber or timestamp. Now resolves the declared dependency
  closure (40 components). Both workflows also called `cyclonedx-py
  requirements`, which could never run here; `release.yml` had no fallback, so
  a real tagged release would have failed at that step.
- **Version claims disagreed**: CITATION.cff and SECURITY.md described 0.1.x
  while the package was 0.2.1.


### Added
- **External trace ingestion** (`tooltrace ingest`, `tooltrace.ingest`): convert
  traces produced outside the harness into ToolTrace trace events so they can be
  classified with the failure taxonomy, replayed and scored by the standard
  pipeline. Formats: OTel GenAI semantic-convention spans (`otel-spans`) and
  plain assistant-step records (`openai-steps`). Observability platforms become
  data sources instead of competitors.
- **pytest integration** (`pytest11` entry point, auto-enabled on install):
  `tooltrace_runner`, `run_tooltrace(...)` and `assert_tooltrace_pass(...)`
  fixtures plus a `tooltrace` marker — run agent tasks as native pytest tests
  with taxonomy-aware diagnostics.
- **Assertion-builder DSL** (`tooltrace.dsl`): typed Python builders mirroring
  every built-in deterministic scorer (`file_exists`, `file_contains`,
  `json_schema`, `command_exit`, …) with authoring-time validation via pydantic;
  includes a `custom()` escape hatch for third-party scorers.
- 17 new tests covering DSL end-to-end scoring, both ingestion formats
  (event-shape, seq monotonicity, JSON-argument decoding), the CLI `ingest`
  command (happy path + usage errors) and real subprocess-level pytest-plugin
  behavior.

## [0.2.1] — Reliability platform, final pass (2026-08-26)

### Changed
- **Repository structure pass:** flat modules organized into cohesive packages —
  `tooltrace/artifacts/` (bundles, reproduction) and `tooltrace/analysis/`
  (comparisons, baselines/trends/snapshots, failure classification, statistics);
  `perturbations`, `replay` and `reports` are now packages. Deprecated shims
  keep every pre-0.2 import path working (`tooltrace.bundles`, `.stats`,
  `.compare`, `.failures`, `.bundles_repro`).
- **Frontend restructure:** numbered continuation modules removed — the team
  console now lives in semantic per-page modules under
  `web/src/pages/workspace/`; the pure pass@k estimator moved to
  `web/src/lib/passAtK.ts`.
- **Tests renamed by domain** (formerly pass-named "gaps" files): failure
  classification, perturbation/SDK, repro/security, scorers/tools, agent
  adapters, CLI commands, docker-sandbox guard.
- Version alignment across `pyproject.toml`, `FRAMEWORK_VERSION`, classifiers
  (Python 3.11–3.14) and this changelog (0.2.0/0.2.1 released); coverage
  `fail_under = 80` enforced from configuration.
- Docs consolidated under `docs/`: product gaps, differentiators and threat
  model (renamed lowercase); broken tables in `feature-status.md` repaired;
  module map synchronized with reality (including the argparse CLI correction).

### Fixed
- **Hermetic test imports:** `tests` is now a regular package, so conftest
  imports can never resolve against a foreign `tests` namespace package on
  `sys.path` (previously broke 6 test modules on machines with other
  checkouts).
- **Real hook-order bug** in Reliability Trends (conditional `useMemo`
  after early returns), caught by the newly enforced react-hooks rules.

### Added
- **CLI signature workflows:** `tooltrace perturb` (safe fault injection with
  recovery-rate measurement and a `--min-recovery-rate` CI gate) and
  `tooltrace trace` (checksum-verified terminal trace inspection with
  filtering and assertions-only view). Both were promised by the README but
  had no implementation; they now exist with tests and smoke coverage (190
  Python tests total).
- **Team console frontend:** 14 self-hosted routes — workspace dashboard,
  experiments + builder + live SSE monitor, workers/capacity, baselines &
  regressions, Task Authoring Studio (client-side lint pre-checks mirroring
  `tooltrace lint`, assertion workflow graph), publication review queue,
  users & service accounts, policies & budgets, audit log, webhooks,
  retention/settings and system health. Backed by the same dual-mode data
  layer: static validated JSON on Pages or the self-hosted REST/SSE server;
  DEMO-labeled fixtures for offline preview only.
- **Charts:** dependency-free accessible SVG charts — multi-series line,
  histogram, scatter, domain×agent heatmap, utilization rings; wired into
  leaderboard, trends, efficiency pages and workers.
- **Frontend resilience:** route-level code splitting, error boundary,
  offline banner, virtualized Trace Explorer for large traces.
- **E2E & accessibility:** 23 Playwright tests (route smoke with zero-console-
  error assertions, axe wcag2a/2aa serious-violation gate, keyboard nav) plus
  18 vitest unit/component tests; ESLint actually installed and enforced.
- **Docs:** migration guide (protocol v1→v2), enterprise deployment,
  plugins & extensions, schemas & protocols, recipes; docs map updated.

### Changed
- CI: dependency audit is now a blocking gate (`pip-audit --skip-editable`,
  no more `|| echo` escapes); Windows/macOS test matrix added; frontend job
  runs lint + unit + e2e/a11y against the production build.
- Release: new tag-triggered pipeline (validate → test → build sdist/wheel →
  build frontend → CycloneDX SBOM → SHA256SUMS → SLSA provenance attestation
  → GitHub Release); PyPI publishing only via an explicit Trusted Publishing
  environment flag. All action pins verified against the GitHub API.
- WCAG AA color tokens: light muted/accent/warn darkened to pass contrast
  (failures found by the new axe scans).

## [0.2.0] — Second transformation pass (2026-08-23)

### Added
- **Protocol & data governance:** task protocol v2 (domain, difficulty, deterministic
  seeds, capability requirements, allowed side effects, scoring contracts) with v1
  migration readers; task provenance manifests; semver task-pack indexes with
  compatibility ranges; contamination-aware metadata; cross-pack fingerprint dedup;
  deterministic synthetic task-generation SDK.
- **Task packs & interfaces:** coding, OS/fileops, database, mock-API workflow,
  local web environment, knowledge-retrieval, spreadsheet/data-transform, git
  workflow, DevOps fixtures and defensive-security packs; multimodal attachment
  schema; voice-agent fixture interface; desktop/GUI and mobile abstractions;
  human-in-the-loop states; dual-control tasks; multi-agent role definitions;
  adversarial-but-safe robustness tasks; long-horizon checkpointed tasks;
  prerequisites and resource budgets.
- **Quality gates:** `tooltrace lint` (ambiguous scoring, unreachable assertions,
  undeclared side effects, missing cleanup, unsafe network), `tooltrace dry-run`,
  suite manifests, fixed/stratified/seeded sampling policies with recorded
  selection manifests.
- **Metrics:** pass@k / pass^k with confidence intervals; trajectory efficiency
  (per step/tool-call/token/wall-time); recovery vs agent-caused failure metrics;
  policy-compliance scoring; side-effect correctness; change minimality;
  verification quality; loop/stagnation detection; hallucinated-resource metrics;
  context retention; abstention calibration; outcome-vs-trajectory dual scoring;
  judge-independent deterministic scoring with judge dependency reported.
- **Adapters & integrations:** multi-judge disagreement reporting + calibration
  sets; scorer plugin API v2 with conformance tests; provider metadata
  normalization; OpenAI-/Anthropic-/Gemini-compatible and local subprocess
  adapters (optional extras); MCP client support + server conformance fixtures;
  A2A abstraction hook; capability negotiation; recorded retry/backoff;
  rate-limit telemetry; per-adapter doctor checks; env/keychain secret resolution;
  explicit price-table cost accounting.
- **Execution engine:** experiment manifests; distributed coordinator with
  deterministic run IDs; bounded-concurrency local execution; worker capability
  inventory; resumable checkpoints; cancellation/cleanup; failure-isolated
  workers; fair queues; sharding/merge utilities.
- **Analysis & reproducibility:** cohort compatibility enforcement; baselines at
  suite/domain/task/metric level; trend analysis with composition warnings;
  paired-run analysis; effect-size reporting; bootstrap/Bayesian extras;
  reliability frontier charts; failure clustering; root-cause drill-down;
  reproducibility score; full/partial replay; redaction policies; trace
  compression/streaming; binary artifact manifests; trace schema migrations;
  signed bundles; tamper-evident checksums; invalidation/supersession records;
  snapshot generation/verification (`tooltrace snapshot`); cohort-safe
  leaderboards; anti-gaming checks.
- **Infrastructure:** image-digest provenance; Podman support; Windows-native
  sandbox interface; Kubernetes job-runner backend; resource telemetry; network
  policy profiles (offline / local-fixtures-only / allowlist); deterministic clock
  injection; fault-injection framework; chaos/recovery suites; harness self-test
  (`tooltrace self-test`); authoring studio APIs; catalog metadata; contribution
  quality checks.
- **Self-hosted server** (`tooltrace server`): workspaces with strict tenant
  scoping; RBAC (viewer/runner/task_author/reviewer/admin/service_account);
  hashed rotatable API tokens; local-dev auth + OIDC/SAML hooks; policy-as-code;
  approval workflows; hash-chained immutable audit log; quotas (HTTP 429);
  HMAC-signed webhooks with retries; retention with legal-hold exemptions; REST +
  SSE + Prometheus `/metrics` + `/healthz` + `/readyz` + `/openapi.json`;
  request body size limits; backup/export tooling; air-gapped posture docs.
- **Frontend:** Trace Explorer (filterable expandable timeline, raw JSONL
  download), Recovery Analysis, Cost·Latency·Efficiency, Dataset/Snapshot browser,
  Plugin Catalog; nav/routes wired into the existing console.
- **Docs:** documentation map, getting started, CLI reference, architecture
  pipeline diagram, self-hosting guide, troubleshooting/FAQ; competitive analysis
  with verified evidence matrix (`docs/competitive-analysis.md`,
  `data/competitive-capabilities.json`), `PRODUCT_GAPS.md`, `DIFFERENTIATORS.md`.

### Changed
- CI action pins bumped to current immutable SHAs (setup-python, codeql-action,
  configure-pages) per Dependabot #18.
- README gained a Documentation section linking the full hierarchy.

### Security
- Secret scan clean across all paths; request body limits on server endpoints;
  tenant-scoped authorization tests; offline-by-default sandbox network posture.

### Removed
- Stray generated artifacts from version control (`results/_refcheck.txt`).

## [0.1.0] — Initial public beta

First release: typed core engine, CLI (run/benchmark/showdown/compare/baseline/
regression/validate/reproduce/report/export/serve/task), scripted + subprocess +
OpenAI-compatible agents, temp-workspace and Docker sandboxes, deterministic
scorers, `.tooltrace` bundles with checksums, React frontend, tests and CI.