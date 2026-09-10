# Evidence dossier

```bash
tooltrace evidence --bundles results --out audit/
```

Writes `evidence.json` and `evidence.md`: every run, whether its checksums
verify, and what those runs do and do not evidence against the obligations for
high-risk AI systems.

## This is evidence, not a compliance determination

The remaining EU AI Act provisions became applicable on **2 August 2026**, and
the phrase every compliance guide repeats is that an organisation must
*demonstrate* compliance rather than claim it. A checksummed, reproducible
`.tooltrace` bundle is already an evidence artifact for that.

**It is not a verdict, and this tool will not produce one.** Whether a system
meets its legal obligations is an organisational determination about that system
in its deployment context, made by people accountable for it. A "compliant"
verdict emitted by a benchmark would be actively misleading in a domain carrying
€35M penalties, and the fact that a machine produced it would lend it unearned
authority. A test asserts no rendering contains such a claim.

The Article references are pointers so a reviewer can find the relevant text.
They are not legal advice.

## Gaps are given equal prominence

Every obligation carries `evidence` **and** `gaps`, and the gaps are never empty
by construction: an obligation with nothing stated against it would read as
fully satisfied. The dossier says, among other things:

- a benchmark exercises the failure modes its packs encode — it is not a hazard
  analysis of your deployment;
- it documents the *evaluation*, not the system: intended purpose, training data
  and human-oversight measures are outside what a run can evidence;
- checksums are **tamper-evident, not tamper-proof** — they detect modification,
  they do not establish who produced a bundle;
- a success rate from fewer than 30 runs has a wide interval and is flagged as
  such;
- when no `security/` tasks ran, the absence of cybersecurity evidence is stated
  rather than passed over.

## The hash chain

Runs are chained: each entry commits to the digest before it, so a run that is
**removed or reordered** is detectable, not only one that is modified.
`verify_chain` recomputes it, and the tests break the chain three ways —
altering a run, deleting one, and replacing the head — because a chain that
cannot detect tampering is decoration.

A bundle too damaged to parse is **recorded as unreadable and unverified**
rather than crashing the report. An audit most needs to see the corrupt
artifact, not lose the report over it; the CLI also warns on stderr and lists it
in `unverified`.

## Reproducibility

The generation timestamp is injected rather than read from the clock, so two
dossiers built from the same bundles are byte-identical and can be diffed.

## The trust ladder, and what it takes to climb it

`TrustState` declares four levels -- `LOCAL`, `COMMUNITY_VALIDATED`,
`REPRODUCED`, `MAINTAINER_VERIFIED` -- with a docstring promising they are "never
implied without evidence". Until now every bundle this project has written was
`LOCAL` and `promote_trust` had no caller outside the test suite: the upper three
were labels nothing could produce. That is worse than three levels honestly held,
because a reader who sees four states reasonably assumes some bundle is in one of
them.

`tooltrace attest` is the missing evidence. It re-runs a bundle, records who did
it and on what, and binds the record to that bundle's manifest digest.

**Self-attestation is not reproduction.** A bundle re-run on the machine that
produced it demonstrates that the machine is deterministic, which is a real but
much weaker claim, and conflating the two would make `REPRODUCED` mean nothing.
The hardware profile in each attestation is compared against the one in the
bundle's `environment.json`, and a same-machine re-run stays `LOCAL` with a
reason saying so.

| Evidence | Highest state |
|---|---|
| Nothing | `LOCAL` |
| Reproduced on the same machine | `LOCAL` |
| Reproduced elsewhere, unsigned | `COMMUNITY_VALIDATED` |
| Reproduced elsewhere, signed | `REPRODUCED` |
| A person with authority looked | `MAINTAINER_VERIFIED`, never awarded by this code |

An attestation carries the manifest digest, so it cannot be moved to another
bundle -- an attestation that could be copied would be a sticker rather than
evidence -- and promoting a bundle rewrites its manifest, which stales every
attestation made before. The command says so rather than rewriting them, because
rewriting them would be forging them.

## A system card that cannot flatter

A hand-written system card becomes marketing: the capabilities section fills up,
the limitations section reads "may occasionally make mistakes", and the
*unmeasured* section does not exist. `tooltrace card` generates one from recorded
runs, and inverts those incentives.

The rule that does the work: **a task with fewer than ten runs is neither a
capability nor a limitation.** A 3-run 100% and a 3-run 0% both land in
"insufficiently measured", which exists precisely so that neither neighbouring
section absorbs them. Runs in the middle -- succeeding sometimes -- go there too.

The *not measured* section is the one a benchmark can fill best, because what was
never measured is exactly what a benchmark knows: unpriced runs, the OWASP
categories with no runnable task, absent inference timings, and the standing
caveat that a benchmark says nothing about failure modes its packs do not encode.

## Auditing your own evidence

The EU AI Act's operative phrase is that an organisation must *demonstrate*
compliance rather than claim it. `tooltrace self-audit` turns that back on the
evidence itself: would what you hold actually demonstrate anything?

It produces a checklist and a list of gaps, and deliberately **no percentage**.
"Evidence completeness: 73%" is a number that ends up on a slide, and there is no
weighting of these checks that would mean anything to a regulator. A checklist
with named gaps cannot be summarised into a grade, which is the point.

Run against this repository's own bundles it currently fails four of seven
checks, including "reproduced by someone else". An audit that passes its author's
own evidence is not an audit.

## Other control sets: NIST AI RMF and ISO/IEC 42001

`--framework nist-ai-rmf` and `--framework iso-42001` re-file the **same facts**
in another vocabulary. Nothing is re-derived: two mappings of one run set that
could disagree would be the failure a mapping exists to prevent.

Every mapping reports three states, and the third is the reason the feature
exists:

| State | Meaning |
|---|---|
| `evidenced` | These runs provide evidence for this control |
| `not_run` | This project could evidence it and these runs did not |
| `out_of_scope` | **No benchmark can evidence it**, ever |

A mapping that quietly listed only the controls it could reach would read, to a
reviewer skimming a table, as a project that covers NIST AI RMF. It does not and
it cannot:

- **NIST AI RMF.** GOVERN is organisational in its entirety -- policies,
  accountability, culture -- and no run evidences a policy. MAP is about context
  and intended use, which is a property of your deployment. MEASURE is where a
  benchmark lives, and it covers some categories there and not others. MANAGE is
  about what you *do* with a finding.
- **ISO/IEC 42001.** It certifies a *management system*. Clauses 4-10 are
  leadership, planning, competence and continual improvement, and no evaluation
  output speaks to them. What a harness contributes is evidence for a handful of
  Annex A controls, which an auditor reads alongside everything else. This is not
  a certification and cannot be presented as progress toward one.

## When each obligation became evidenceable

`--history` answers a narrower question than the changelog: from which release
could this tool speak to a given obligation *at all*? A dossier produced before
a capability shipped is silent on that obligation for a reason that has nothing
to do with the agent, and a reviewer cannot otherwise tell the two apart.

Releases that added nothing are listed too. Omitting them would make the record
read as steady regulatory progress rather than as a record. The list is
machine-checked against `CHANGELOG.md` in both directions -- a regulatory
document that has quietly drifted from the release history is worse than none,
because it is the one a reviewer would trust.

Becoming *able to evidence* an obligation is not satisfying it, and the output
says so.

## Before you share a bundle: `tooltrace redaction`

Sharing a trace means sharing whatever the agent read and wrote. The report says
what was removed on capture, what personal-data shapes survive, and -- at the
same prominence -- two things it will not say:

**A clean scan is not proof of absence.** Every detector matches a *shape*. An
email address has one. A person's name does not, and neither does a sentence
about them, and neither does a medical record number that looks like an order
id. "No PII found" would be read as "safe to publish" and would be wrong in
exactly the cases that matter most. The `safe_to_publish` field is `null`,
deliberately, and the categories with no shape are listed by name in every
output.

**It is not differential privacy.** DP means calibrated noise under an epsilon
budget. A bundle's entire value is that a third party can reproduce it byte for
byte and get the same checksums; noise would break the reproduction the artifact
exists to support. The two properties are in direct conflict, so this does
redaction and says so rather than borrowing a word that implies a guarantee.

Personal-data findings never fail the command -- whether an email address in a
trace is a problem depends on whose it is and where the bundle is going, and a
tool that refused to proceed would be making that call for the publisher. A
*secret* still matching after sanitisation does fail it, with exit code 9,
because that is a defect in the sanitiser rather than a property of the run.

## Auditor mode

An external reviewer needs to see the evidence, must not be able to change it,
must lose access when the audit ends, and must be able to tell -- as must anyone
they show a screenshot to -- that they were looking at a shared view.
`auditor_grant` issues exactly that: a read-only role, an absolute expiry the
token store enforces, and a watermark carried **on the token** so every response
served under it can include it. A watermark applied at render time is one
somebody can render without.

The fix underneath was that expiry had never been enforced at all. The store
recorded `expires_hint_days` and `verify` returned the record whatever its age,
so every token this server ever issued was permanent. A grant "for the duration
of the audit" that outlives the audit is how a temporary reviewer becomes a
permanent one, and the field name made it look deliberate.
