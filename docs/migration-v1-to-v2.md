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

v2 = migrate_v1_to_v2(v1_dict)   # accepts dict or v1 TaskDefinition
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
