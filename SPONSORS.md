# Sponsors

ToolTrace Bench is Apache-2.0, built in the open, and has no company behind it.

**[Sponsor @webdevsamran on GitHub →](https://github.com/sponsors/webdevsamran)**

---

## What sponsorship does not buy

This belongs at the top rather than the bottom, because it is the first question
a reader should ask of any benchmark that accepts money.

**Sponsorship buys no influence over results.** There is no mechanism by which it
could:

- scoring is **deterministic** — assertions run against the execution trace and
  the final workspace, never against a model's opinion of its own work;
- the public leaderboard is **generated** from bundles that pass
  `tooltrace verify`, by a script in this repository, from data in this
  repository;
- every bundle is **checksummed and reproducible**, so any published number can
  be independently re-run by anyone who disagrees with it;
- the anti-gaming checks — leaked expected values, modified fixtures, skipped
  assertions — run on **every** bundle, including any a sponsor produced.

If a sponsor's agent scores badly, that is what the table will say. A benchmark
that would bend is not worth sponsoring, and would not be worth reading.

**Sponsorship is not a support contract.** There is no SLA, no private issue
queue and no guaranteed response time. Bugs are triaged on severity, not on who
reported them.

## What it funds, in priority order

1. **Keeping the security suite current.** OWASP's Top 10 for Agentic
   Applications moves, and a prompt-injection corpus that is a year old measures
   last year's attacks. This is maintenance that never finishes and nobody
   volunteers for.

2. **Compliance mappings as the deadlines arrive.** The remaining EU AI Act
   provisions became applicable on 2 August 2026; Annex III systems must comply
   by 2 December 2027 and Annex I by 2 August 2028. Each of those changes what an
   evidence dossier has to contain.

3. **Task packs in regulated domains.** Finance, healthcare and legal packs need
   review by people who actually work in those fields, and that review is not
   free.

4. **Reproduction infrastructure.** A benchmark result nobody has independently
   re-run is a claim. Making reproduction cheap is what turns it into evidence.

## Ways to help that cost nothing

Listed second only because the section above has to answer the money question
first. These matter as much.

| Contribution | How |
|---|---|
| **Reproduce a published result** | `tooltrace attest <bundle>` — an independently re-run result is the difference between a claim and evidence |
| **Contribute a task pack** | Packs are YAML; see [CONTRIBUTING.md](CONTRIBUTING.md). A pack from a domain you work in is worth more than ten from one you don't |
| **Report an honest failure** | A case where the harness scored something *wrong* is worth more than a feature request, and will be treated that way |
| **Improve the documentation** | Every claim in this repository is machine-checked against the code. If you find one that is not, that is a bug in the checking |
| **Star the repository** | It is the only distribution signal this project has |

## Current sponsors

None yet — this file exists so that the first one has somewhere to appear, and
so the terms above are on the record before rather than after.

Sponsors are credited here by name and link unless they ask not to be. Ask, and
you will not be listed; nothing changes either way.

---

## For organisations

If your team is evaluating agents against the EU AI Act, NIST AI RMF or ISO/IEC
42001, the parts of this project you are most likely to need are:

- [`docs/evidence-dossier.md`](docs/evidence-dossier.md) — what the dossier
  records, and what it explicitly refuses to claim
- [`docs/self-hosting.md`](docs/self-hosting.md) — RBAC, policy-as-code, quotas,
  signed webhooks, hash-chained audit
- [`docs/threat-model.md`](docs/threat-model.md) — the sandbox's honest limits
- [`docs/feature-status.md`](docs/feature-status.md) — every capability, graded,
  machine-checked, including the ones that do not exist

Open an issue for procurement questions. There is no sales contact, because
there is nothing to sell — the whole thing is Apache-2.0 and runs on your own
hardware.
