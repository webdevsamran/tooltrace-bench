"""Produce real sample bundles for the frontend: run the deterministic
scripted agent over a representative task subset with --runs N.

The subset includes the two shipped security packs. Without them the dataset has
no adversarial runs at all, so the leaderboard's security axis reads "not
measured" for every agent, the security-posture view has nothing to show, and
the evidence dossier records "cybersecurity evidence is absent" as a gap. Those
are honest statements about a dataset that never attacked anything -- but the
packs exist and run, so the honest fix is to run them rather than to keep
reporting their absence.

The scripted agent resists both, which is not a claim about any real agent: it
follows a fixed script and never reads the injected instruction. What the runs
demonstrate is that the measurement works end to end, which is what a sample
dataset is for.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tooltrace.cli.main import main as cli_main

TASKS = ",".join(
    [
        "file-editing/fix-config-typo",
        "json-csv-transform/users-to-csv",
        "failure-recovery/retry-after-tool-failure",
        "security/indirect-injection-exfiltration",
        "security/indirect-injection-direct-harm",
        "security/instruction-hierarchy",
        "security/excessive-agency-cleanup",
    ]
)


def main() -> int:
    shutil.rmtree("results", ignore_errors=True)
    Path("results").mkdir(exist_ok=True)
    code = cli_main(["benchmark", "--runs", "2", "--task", TASKS, "--out", "results", "--summary"])
    if code != 0:
        print("benchmark failed", file=sys.stderr)
        return 1
    return cli_main(
        ["report", "--bundles", "results", "--format", "html", "--output", "results/report.html"]
    )


if __name__ == "__main__":
    raise SystemExit(main())
