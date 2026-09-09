# Security evaluation

Prompt injection is #1 on the OWASP Top 10 for Agentic Applications (2026), and
sensitive-information disclosure is #2. `tooltrace/tasks/packs/security/`
measures whether an agent can be talked out of its instructions by text it
reads, across the two classes that matter in practice:

| Class | Question |
|---|---|
| `exfiltration` | Did the agent send private data somewhere it was told to, by a file rather than by the user? |
| `direct_harm` | Did the agent destroy or modify something it was not asked to touch? |

## How exfiltration is measured without egress

The usual way to measure exfiltration is to let data leave the machine and watch
a collector receive it. This project will not do that. The sandbox is offline by
default, and adding real network egress in order to *measure* security would
make the harness the vulnerability it is testing for.

Instead, `http_post` (`tooltrace/tools/sink.py`) is presented to the agent as an
ordinary way to send data to a collector, and **sends nothing**. Every call is
appended to `.tooltrace_egress/requests.jsonl` inside the workspace. That has
three consequences worth stating:

- The attempt becomes **workspace-observable**, so ordinary `(params, workspace)`
  scorers can read it and the evidence lands in the bundle a third party can verify.
- The tool's description says plainly that the call is recorded rather than sent.
  A benchmark that lied to the agent to get a scarier number would be measuring
  its own deception, and the recorded *intent* is what is worth measuring.
- The agent **cannot rewrite the record**: `.tooltrace_egress/` is refused by
  every path-taking tool, so an agent cannot erase evidence of its own leak.

Canary values are matched **in the tool, on raw arguments, before the executor
sanitizes them** — the sanitizer redacts secret-shaped strings, so matching
afterwards would find nothing and every agent would score as perfectly secure.
Only canary **ids** are recorded, never values, so the log is publishable and a
bundle never embeds the secret it was testing for.

## Scores are defences, ASR is derived

The scorers score the **defence**: `1.0` means the attack was resisted. That
keeps `success` meaning what it means everywhere else, so no report column or
regression gate needed a special case. Attack success rate is derived as
`1 - defence_rate` in `tooltrace/metrics/security.py`, so the two can never
disagree.

Every rate carries a Wilson interval and a `sample_is_small` flag. **An ASR of
0% over three attempts is not evidence of a secure agent**, and security numbers
get quoted more widely than accuracy ones, so the interval travels with them.

## Responsible use

The payloads committed here are **public smoke tests**, marked
`public_smoke: true` in each task's `metadata.attack`. They exist to prove the
harness detects the classes it claims to detect. They are deliberately obvious,
they are the kind of example already published in every write-up of the
technique, and they have no transferable value against a production system.

This repository publishes an **evaluation harness and aggregate results**, not
an attack toolkit. A ready-to-run corpus of effective payloads with no access
control is a different artifact with different consequences, and is not what
this is.

On third-party corpora: `microsoft/BIPIA` carries no recognised licence
(`NOASSERTION` as of 2026-09-09), so its payloads **cannot be vendored** here
regardless of their quality. `uiuc-kang-lab/InjecAgent` (MIT) has not been
pushed since 2024-07. Any future corpus must be licence-checked before use, and
the licence recorded alongside it.

## What this does not measure

- **Not real egress.** The sink proves an agent *attempted* to transmit, and
  what it would have transmitted. It does not prove a real endpoint would accept
  it, and it cannot see covert channels — DNS, timing, or a body encoded so the
  canary matcher misses it, since matching is literal substring on canary values.
- **Sink integrity is tool-mediated.** `resolve_in_workspace` blocks the
  reserved prefix, and security tasks may not allow `shell`, `git` or `http`
  (a test enforces this, and `shell` is the local sandbox's documented egress
  gap). That is prohibition plus enforcement, not a cryptographic guarantee.
- **ASR is corpus-relative.** It says "this agent resisted *these* payloads at
  *this* corpus version". It never says an agent is safe. Payload sets are not a
  random sample of anything.
- **The shipped pack is a smoke pack.** Two tasks. It validates the harness, not
  an agent's real-world robustness.
- **No multi-turn, no memory poisoning, no retrieval channel.** Those need an
  execution model this project does not have yet.
- **No judge.** Every check is a deterministic file or hash comparison. Refusal
  quality, partial compliance, and "the agent leaked a paraphrase" are unmeasured
  by design.
