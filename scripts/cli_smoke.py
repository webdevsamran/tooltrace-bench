"""End-to-end CLI smoke test; writes a transcript to results/_cli_smoke.txt."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tooltrace.cli.main import main as cli_main

NL = chr(10)
OUT = Path("results/_smoke")
transcript: list[str] = []


def run(label: str, argv: list[str], expect: int) -> None:
    code = cli_main(argv)
    status = "OK" if code == expect else f"UNEXPECTED({code} != {expect})"
    transcript.append(f"[{status}] {label}")


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    run("doctor", ["doctor", "--json"], 0)
    run("agents", ["agents"], 0)
    run("tasks", ["tasks"], 0)
    run(
        "run+bundle",
        ["run", "--task", "file-editing/fix-config-typo", "--out", str(OUT)],
        0,
    )
    bundles = sorted(OUT.glob("*.tooltrace"))
    assert len(bundles) == 1, f"expected 1 bundle, got {bundles}"
    b1 = str(bundles[0])
    run(
        "benchmark runs=2",
        [
            "benchmark",
            "--runs",
            "2",
            "--task",
            "file-editing/fix-config-typo,json-csv-transform/users-to-csv",
            "--out",
            str(OUT),
            "--summary",
        ],
        0,
    )
    bundles = sorted(OUT.glob("*.tooltrace"))
    assert len(bundles) >= 5, f"expected >=5 bundles, got {len(bundles)}"
    base, curr = str(bundles[0]), str(bundles[1])
    run("compare", ["compare", "--baseline", base, "--current", curr, "--json"], 0)
    run("baseline", ["baseline", "--name", "smoke", "--bundle", base], 0)
    run(
        "regression pass",
        [
            "regression",
            "--baseline",
            base,
            "--current",
            curr,
            "--thresholds",
            json.dumps({"score": {"min_delta": -0.05}}),
        ],
        0,
    )
    run("validate packs", ["validate", "--path", "tooltrace/tasks/packs"], 0)
    run("reproduce no-rerun", ["reproduce", b1, "--no-rerun"], 0)
    run("report md", ["report", "--bundles", str(OUT), "--format", "md"], 0)
    run(
        "showdown",
        [
            "showdown",
            "--agents",
            "scripted",
            "--runs",
            "1",
            "--task",
            "file-editing/fix-config-typo",
        ],
        0,
    )
    # regression failure path must exit 8
    code = cli_main(
        [
            "regression",
            "--baseline",
            base,
            "--current",
            curr,
            "--thresholds",
            json.dumps({"score": {"min_delta": 0.5}}),
        ]
    )
    transcript.append(
        f"[{'OK' if code == 8 else 'UNEXPECTED(' + str(code) + ')'}] "
        "regression threshold-fail exits 8"
    )

    text = NL.join(transcript)
    print(text)
    (Path("results") / "_cli_smoke.txt").write_text(text + NL, encoding="utf-8")
    return 0 if all("[OK" in t for t in transcript) else 1


if __name__ == "__main__":
    raise SystemExit(main())
