"""The README must not describe behaviour the code does not have.

This repository shipped a README section headed "A real sample run", prefaced
"no fabricated numbers", showing output for a task (`fileops/copy-and-rename`)
that does not exist, with score components no scorer emits and a `wall_ms`
traceable to the frontend's demo fixture. The quickstart alongside it used
that same nonexistent task and a `--pack` flag the CLI has never had.

For a benchmarking tool, that is the most damaging possible defect: every
number it publishes is only worth what its honesty is worth. These tests make
the README checkable by machine so it cannot rot back.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_README = (_ROOT / "README.md").read_text(encoding="utf-8")

# Fields that legitimately vary between runs.
_NONDETERMINISTIC = {
    "run_id",
    "wall_ms",
    "tool_ms",
    "model_ms",
    "started_at",
    "finished_at",
}


def _real_task_ids() -> set[str]:
    ids: set[str] = set()
    for path in (_ROOT / "tooltrace" / "tasks" / "packs").rglob("*.yaml"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("id:"):
                ids.add(line.split(":", 1)[1].strip())
    return ids


def _task_ids_cited_in_readme() -> set[str]:
    return set(re.findall(r"--task ([a-z0-9-]+/[a-z0-9-]+)", _README))


def test_every_task_the_readme_names_actually_exists() -> None:
    """The `fileops/copy-and-rename` regression, pinned."""
    real = _real_task_ids()
    cited = _task_ids_cited_in_readme()
    assert cited, "expected the README to cite at least one task id"
    unknown = sorted(cited - real)
    assert not unknown, (
        f"README documents task id(s) that do not exist: {unknown}. Real ids: {sorted(real)}"
    )


def test_every_pack_the_readme_tabulates_actually_exists() -> None:
    packs = {p.name for p in (_ROOT / "tooltrace" / "tasks" / "packs").iterdir() if p.is_dir()}
    section = _README.split("## Task types shipped", 1)[1].split("## ", 1)[0]
    tabulated = set(re.findall(r"^\| `([a-z0-9-]+)` \|", section, re.M))
    assert tabulated, "expected a pack table in the README"
    unknown = sorted(tabulated - packs)
    assert not unknown, f"README tabulates pack(s) that do not exist: {unknown}"
    missing = sorted(packs - tabulated)
    assert not missing, f"README omits shipped pack(s): {missing}"


def _readme_sample() -> dict:
    block = _README.split("```console", 1)[1].split("```", 1)[0]
    return json.loads(block[block.index("{") :])


def test_readme_sample_command_matches_its_output() -> None:
    """The console block's command must be the one that produced its output."""
    block = _README.split("```console", 1)[1].split("```", 1)[0]
    command = next(line for line in block.splitlines() if line.startswith("$ "))
    sample = _readme_sample()
    assert sample["result"]["task_id"] in command, (
        "the sample output is from a different task than the command shown"
    )


@pytest.mark.slow
def test_readme_sample_is_reproducible(tmp_path: Path) -> None:
    """Run the documented command and diff it against the documented output.

    Every deterministic field must match exactly. This is what makes the
    "captured, not hand-written" claim in the README verifiable rather than
    something a reader has to take on trust.
    """
    sample = _readme_sample()["result"]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tooltrace.cli.main",
            "run",
            "--task",
            sample["task_id"],
            "--agent",
            sample["agent"],
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    live = json.loads(proc.stdout)["result"]

    mismatches = {
        key: (value, live.get(key))
        for key, value in sample.items()
        if key not in _NONDETERMINISTIC and live.get(key) != value
    }
    assert not mismatches, f"README sample no longer matches real output: {mismatches}"

    invented = [key for key in sample if key not in live]
    assert not invented, f"README sample contains fields the tool never emits: {invented}"


def _documented_invocations() -> list[tuple[str, str, list[str]]]:
    """(source file, subcommand, flags) for every `tooltrace ...` line in docs."""
    found: list[tuple[str, str, list[str]]] = []
    for doc in sorted(_ROOT.glob("*.md")) + sorted((_ROOT / "docs").glob("*.md")):
        text = doc.read_text(encoding="utf-8")
        for raw in text.splitlines():
            line = raw.strip().lstrip("$ ").strip()
            if not line.startswith("tooltrace "):
                continue
            tokens = line.split()
            if len(tokens) < 2 or tokens[1].startswith("-"):
                continue
            # `task scaffold`, `task validate` etc. nest one level deeper.
            rest = tokens[2:]
            sub = tokens[1]
            if rest and not rest[0].startswith("-"):
                sub = f"{sub} {rest[0]}"
                rest = rest[1:]
            flags = [t for t in rest if t.startswith("--")]
            found.append((doc.name, sub, flags))
    return found


def test_every_documented_flag_exists_on_its_subcommand() -> None:
    """Docs used --pack, --suite, --agent-a, --reps and --from; none existed.

    Parsing each subcommand's real argparse definition is what makes this
    checkable rather than a matter of someone remembering to update prose.
    """
    from tooltrace.cli.main import build_parser

    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    )
    problems: list[str] = []
    for source, subcommand, flags in _documented_invocations():
        head, _, tail = subcommand.partition(" ")
        sub = subparsers.choices.get(head)
        if sub is None:
            problems.append(f"{source}: `tooltrace {head}` is not a subcommand")
            continue
        if tail:
            nested = next((a for a in sub._actions if hasattr(a, "choices") and a.choices), None)
            if nested is not None and tail in nested.choices:
                sub = nested.choices[tail]
            elif nested is not None:
                problems.append(f"{source}: `tooltrace {head} {tail}` is not a subcommand")
                continue
        known = {opt for action in sub._actions for opt in action.option_strings}
        for flag in flags:
            name = flag.split("=", 1)[0]
            if name not in known:
                problems.append(f"{source}: `tooltrace {subcommand} {name}` -- no such flag")
    assert not problems, "documented commands that cannot run:\n  " + "\n  ".join(problems)


def test_documented_scorer_count_matches_the_registry() -> None:
    """docs/plugins.md states a built-in scorer count; keep it derived."""
    import re

    import tooltrace.scoring.builtin  # noqa: F401  (registers the built-ins)
    from tooltrace.core.registry import scorer_registry

    registered = len(scorer_registry.names())
    doc = (_ROOT / "docs" / "plugins.md").read_text(encoding="utf-8")
    match = re.search(r"(\d+) built-in scorers", doc)
    assert match, "docs/plugins.md no longer states a scorer count"
    assert int(match.group(1)) == registered, (
        f"docs/plugins.md says {match.group(1)} built-in scorers; the registry has {registered}"
    )


def test_documented_platforms_match_what_ci_runs() -> None:
    """The README's platform table is a claim CI must actually back.

    Declaring support for a platform or Python version nothing tests is the
    same class of defect as a fabricated sample: it is a statement about
    behaviour with nothing behind it. pyproject classified 3.11 through 3.14
    while CI tested only 3.12.
    """
    import yaml

    workflow = yaml.safe_load(
        (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]

    tested_os = {"ubuntu-latest"}
    tested_python: set[str] = set()
    for job in jobs.values():
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        tested_os.update(matrix.get("os", []))
        tested_python.update(str(v) for v in matrix.get("python-version", []))
        for step in job.get("steps", []):
            with_ = step.get("with") or {}
            version = with_.get("python-version")
            if isinstance(version, (str, float, int)) and "${{" not in str(version):
                tested_python.add(str(version))

    section = _README.split("## Supported platforms", 1)[1].split("\n## ", 1)[0]

    for platform in ("ubuntu-latest", "windows-latest", "macos-latest"):
        if f"`{platform}`" in section:
            assert platform in tested_os, (
                f"README claims {platform} support, but no CI job runs on it"
            )

    claimed_python = set(re.findall(r"\b3\.(1[0-9])\b", section))
    for minor in claimed_python:
        version = f"3.{minor}"
        assert version in tested_python, (
            f"README claims Python {version} support; CI tests {sorted(tested_python)}"
        )


def test_pyproject_classifiers_are_all_tested() -> None:
    """A Python classifier is a support claim; CI must cover each one."""
    import tomllib

    import yaml

    with (_ROOT / "pyproject.toml").open("rb") as fh:
        classifiers = tomllib.load(fh)["project"]["classifiers"]
    claimed = {
        c.rsplit(" :: ", 1)[-1]
        for c in classifiers
        if c.startswith("Programming Language :: Python :: 3.")
    }

    workflow = yaml.safe_load(
        (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    tested: set[str] = set()
    for job in workflow["jobs"].values():
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        tested.update(str(v) for v in matrix.get("python-version", []))
        for step in job.get("steps", []):
            version = (step.get("with") or {}).get("python-version")
            if isinstance(version, (str, float, int)) and "${{" not in str(version):
                tested.add(str(version))

    untested = sorted(claimed - tested)
    assert not untested, (
        f"pyproject classifies Python {untested} as supported, but CI never tests them"
    )
