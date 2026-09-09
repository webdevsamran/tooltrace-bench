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
