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
