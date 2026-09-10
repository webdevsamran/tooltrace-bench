# Migration: Task Protocol v1 → v2

Task protocol v2 extends the v1 task spec without breaking existing packs.
This document is the complete field mapping; old readers and old result
bundles remain supported (backwards-compatible readers are covered by tests).

## What changed

| Aspect | v1 | v2 |
|---|---|---|
| Schema root | `TaskDefinition` (`schemas/task.schema.json`) | `TaskDefinitionV2` (`tooltrace/tasks/v2.py`) |
| Categorization | single `category` string from a fixed list | explicit `domain` enum + free `tags` |
| Randomness | implicit / undocumented | explicit `seed` field |
| Side effects | only `network_policy` | `allowed_side_effects` declaration list |
| Scoring | bare assertion list | assertions **plus** `scoring_contract` describing weights/determinism/judge dependency |
| People/steps | none | optional HITL steps, dual-control user actions, agent roles, checkpoint stages |
| Contamination | none | optional `contamination` risk note with assessment date |
| Prerequisites/budgets | timeout/max_steps only | `prerequisites` + resource budget limits |

## Automatic migration

```python
from tooltrace.tasks.v2 import migrate_v1_to_v2

v2 = migrate_v1_to_v2(v1_dict)  # accepts dict or v1 TaskDefinition
```

Migration rules:

- `category` maps onto `domain` through a fixed table
  (`fileops/bugfix/testrepair/refactor → coding`, `docsfix → knowledge`,
  `datatransform/dataanalysis → spreadsheet`, `gitwork → git`,
  `shellwork → os`, `mockapi → api`, and so on — see `_V1_DOMAIN_MAP`).
- Unknown categories fall back to the closest domain rather than failing.
- `difficulty`, `tags`, `objective`, workspace, tools and assertions carry
  over unchanged.
- New fields get safe defaults: no declared side effects beyond network
  policy, deterministic scoring contract, empty contamination/prerequisites.

## Compatibility keys

Result bundles record a compatibility key derived from protocol/trace/result
schema versions (`tooltrace.core.versions.compatibility_key`). Comparisons,
leaderboards and regression baselines refuse to mix incompatible cohorts —
this is why v1-era results never silently blend into v2 rankings.

## Deprecation policy

- v1 files keep loading forever through the migration path; there is no
  forced rewrite.
- New packs should target v2 directly; the authoring SDK scaffolds v2.
- Any future breaking change will bump the schema version again and ship a
  new migration function plus invalidation/supersession records for affected
  published datasets.

## Coming from another benchmark

`tooltrace import` converts a record from SWE-bench, BFCL, tau-bench or
AgentBench into a task here. **Every output is a draft**, and the loss report
attached to it is more of the point than the conversion: a silently converted
SWE-bench instance that scores 0.4 tells a reader nothing unless they know which
half of the original grading survived.

| Source | What converts | What does not |
|---|---|---|
| **SWE-bench** | The oracle. "Hidden tests pass" is the same shape as `tests_pass` | The repository. This sandbox is a temp workspace with declared files, not a checkout at a SHA, and nothing here will clone one. The FAIL_TO_PASS / PASS_TO_PASS split also collapses into one ratio |
| **BFCL** | Nearly all of it. Its grading is a structural match on the emitted call, which is exactly `tool_call_match` | The workspace, because there never was one -- BFCL executes nothing. Its function catalogue is also not registered here, so every call fails as an unknown tool until someone maps them |
| **tau-bench** | The first instruction and the final-state check | The simulated user, which is an LLM this project does not run. The converted task is **strictly easier** than the original |
| **AgentBench** | The OS and DB environments | Everything else. The rest grade with a model judge or a bespoke checker, and are **refused** rather than approximated |

That last row is the rule the module follows everywhere: an approximated oracle
is a task that scores something nobody chose, and a refusal that shows up in the
output is more useful than a task that runs and means nothing. A refused record
is reported alongside the drafts rather than dropped, because a record that
vanished would look like one that was never there.

Nothing fetches anything. Each importer takes a record you already have.
