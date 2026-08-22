"""Produce real sample bundles for the frontend: run the deterministic
scripted agent over a representative task subset with --runs N."""

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
