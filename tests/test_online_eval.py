"""Incremental passes over production traffic, and the window that must not splice.

"Online evaluation" in an offline-first tool means incremental: run it on a
schedule, process what is new, append to a rolling window. Nothing holds a
connection open, because a benchmark that runs a daemon is a benchmark somebody
has to operate.

The load-bearing decision is what the cursor records. Position alone is not
enough: **a window whose sampling policy changed midway is not comparable to
itself.** Switch from uniform-at-1% to stratified and the observed failure rate
jumps because the sample changed, not because anything in production did -- and a
drift report over that window would name a date, describe a convincing shift,
and be entirely an artifact of the pipeline.

So a policy change starts a new window. That is inconvenient exactly once, which
is better than a trend line that lies quietly forever.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tooltrace.core.versions import FRAMEWORK_VERSION
from tooltrace.ingest.online import (
    CONTINUED,
    FIRST_RUN,
    NEW_WINDOW,
    Cursor,
    load_cursor,
    pass_over,
    policy_fingerprint,
    save_cursor,
    windows_are_comparable,
)


def traces(count: int, *, start: int = 0, failure_every: int = 20) -> list[dict[str, Any]]:
    return [
        {
            "trace_id": f"t{i}",
            "steps": 5,
            "failed": bool(failure_every and i % failure_every == 0),
        }
        for i in range(start, start + count)
    ]


# --- incremental ------------------------------------------------------------


def test_the_first_pass_processes_everything(tmp_path: Path) -> None:
    result = pass_over(traces(50), directory=tmp_path)
    assert result["state"] == FIRST_RUN
    assert result["arrived"] == 50
    assert result["already_processed"] == 0


def test_a_second_pass_over_the_same_input_does_nothing(tmp_path: Path) -> None:
    """Re-scoring what is already scored is the cost this exists to avoid."""
    first = pass_over(traces(50), directory=tmp_path)
    save_cursor(tmp_path, first["cursor"])
    second = pass_over(traces(50), directory=tmp_path)
    assert second["state"] == CONTINUED
    assert second["selected"] == 0
    assert second["already_processed"] == 50


def test_only_the_new_traces_are_considered(tmp_path: Path) -> None:
    first = pass_over(traces(50), directory=tmp_path)
    save_cursor(tmp_path, first["cursor"])
    second = pass_over(traces(70), directory=tmp_path)
    assert second["already_processed"] == 50


def test_a_trace_that_arrives_late_is_still_picked_up(tmp_path: Path) -> None:
    """Ids, not a high-water mark.

    Traces do not arrive in order, and a mark would silently skip anything that
    landed after the pass that moved past its position.
    """
    first = pass_over(traces(10, start=10), directory=tmp_path)
    save_cursor(tmp_path, first["cursor"])
    late = pass_over(traces(1, start=0) + traces(10, start=10), directory=tmp_path)
    assert late["already_processed"] == 10
    assert late["arrived"] - late["already_processed"] == 1


def test_a_trace_with_no_id_is_skipped_and_counted(tmp_path: Path) -> None:
    """An id is what makes a pass incremental; without one it would be re-scored
    on every run forever."""
    result = pass_over([{"steps": 3}], directory=tmp_path)
    assert result["unidentified"] == 1
    assert result["selected"] == 0
    assert "re-scored on every run" in result["statement"]


# --- the window ------------------------------------------------------------


def test_changing_the_policy_starts_a_new_window(tmp_path: Path) -> None:
    first = pass_over(traces(50), directory=tmp_path, policy="stratified")
    save_cursor(tmp_path, first["cursor"])
    changed = pass_over(traces(50), directory=tmp_path, policy="uniform")
    assert changed["state"] == NEW_WINDOW
    assert changed["window"] == first["window"] + 1


def test_the_new_window_explains_why_rather_than_only_announcing_it(tmp_path: Path) -> None:
    first = pass_over(traces(10), directory=tmp_path, policy="stratified")
    save_cursor(tmp_path, first["cursor"])
    changed = pass_over(traces(10), directory=tmp_path, policy="uniform")
    assert "not comparable to itself" in changed["reason"]
    assert "artifact of this pipeline" in changed["reason"]


def test_changing_only_the_rate_also_starts_a_new_window(tmp_path: Path) -> None:
    """A different rate is a different sample, whatever the policy is called."""
    first = pass_over(traces(10), directory=tmp_path, policy="uniform", rate=0.01)
    save_cursor(tmp_path, first["cursor"])
    changed = pass_over(traces(10), directory=tmp_path, policy="uniform", rate=0.5)
    assert changed["state"] == NEW_WINDOW


def test_changing_the_seed_also_starts_a_new_window(tmp_path: Path) -> None:
    first = pass_over(traces(10), directory=tmp_path, seed=1)
    save_cursor(tmp_path, first["cursor"])
    changed = pass_over(traces(10), directory=tmp_path, seed=2)
    assert changed["state"] == NEW_WINDOW


def test_an_unchanged_policy_continues_the_window(tmp_path: Path) -> None:
    first = pass_over(traces(10), directory=tmp_path)
    save_cursor(tmp_path, first["cursor"])
    same = pass_over(traces(20), directory=tmp_path)
    assert same["state"] == CONTINUED
    assert same["window"] == first["window"]


def test_a_harness_version_change_starts_a_new_window(tmp_path: Path) -> None:
    """Two halves of a window graded by different code are the same problem as
    two sampling policies."""
    save_cursor(
        tmp_path,
        Cursor(
            seen=set(),
            policy_fingerprint=policy_fingerprint("stratified", 0.01, 0),
            framework_version="0.0.1-ancient",
            windows=1,
        ),
    )
    result = pass_over(traces(10), directory=tmp_path)
    assert result["state"] == NEW_WINDOW
    assert "harness version changed" in result["reason"]


def test_a_new_window_keeps_the_processed_ids(tmp_path: Path) -> None:
    """Starting a window is not a reason to re-score history."""
    first = pass_over(traces(30), directory=tmp_path, policy="stratified")
    save_cursor(tmp_path, first["cursor"])
    changed = pass_over(traces(30), directory=tmp_path, policy="uniform")
    assert changed["already_processed"] == 30


# --- the cursor -------------------------------------------------------------


def test_the_fingerprint_is_exact_rather_than_approximate() -> None:
    """A fuzzy match would let a changed rate through as "close enough"."""
    assert policy_fingerprint("uniform", 0.01, 0) != policy_fingerprint("uniform", 0.0100001, 0)
    assert policy_fingerprint("uniform", 0.01, 0) == policy_fingerprint("uniform", 0.01, 0)


def test_a_cursor_round_trips(tmp_path: Path) -> None:
    original = Cursor(seen={"a", "b"}, policy_fingerprint="f", framework_version="1", windows=3)
    save_cursor(tmp_path, original)
    loaded = load_cursor(tmp_path)
    assert loaded is not None
    assert loaded.seen == {"a", "b"}
    assert loaded.windows == 3


def test_a_corrupt_cursor_starts_a_new_window_rather_than_crashing(tmp_path: Path) -> None:
    """Losing continuity is recoverable; splicing an unknown history into a
    trend line is not."""
    (tmp_path / "online-cursor.json").write_text("{not json", encoding="utf-8")
    assert load_cursor(tmp_path) is None
    assert pass_over(traces(5), directory=tmp_path)["state"] == FIRST_RUN


def test_the_cursor_records_the_current_harness_version(tmp_path: Path) -> None:
    result = pass_over(traces(5), directory=tmp_path)
    assert result["cursor"].framework_version == FRAMEWORK_VERSION


# --- asking the question explicitly ----------------------------------------


def test_two_windows_under_one_policy_are_one_series() -> None:
    a = Cursor(policy_fingerprint="f", framework_version="1")
    b = Cursor(policy_fingerprint="f", framework_version="1")
    assert windows_are_comparable(a, b)["comparable"] is True


def test_two_windows_under_different_policies_are_not() -> None:
    a = Cursor(policy_fingerprint="f", framework_version="1")
    b = Cursor(policy_fingerprint="g", framework_version="1")
    verdict = windows_are_comparable(a, b)
    assert verdict["comparable"] is False
    assert "different policies" in verdict["statement"]


def test_a_version_difference_is_named_with_both_versions() -> None:
    a = Cursor(policy_fingerprint="f", framework_version="0.2.0")
    b = Cursor(policy_fingerprint="f", framework_version="0.3.0")
    assert "0.2.0 vs 0.3.0" in windows_are_comparable(a, b)["statement"]


# --- the CLI ----------------------------------------------------------------


def test_the_cli_leaves_a_cursor_and_skips_on_the_second_pass(tmp_path: Path, capsys) -> None:
    from tooltrace.cli.main import main

    source = tmp_path / "arrivals.jsonl"
    source.write_text("\n".join(json.dumps(t) for t in traces(60)), encoding="utf-8")
    state = tmp_path / "state"

    assert main(["online", "--source", str(source), "--state", str(state), "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["state"] == FIRST_RUN

    assert main(["online", "--source", str(source), "--state", str(state), "--json"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["already_processed"] == 60
    assert second["selected"] == 0


def test_the_cli_writes_only_the_selected_traces(tmp_path: Path, capsys) -> None:
    from tooltrace.cli.main import main

    source = tmp_path / "arrivals.jsonl"
    source.write_text("\n".join(json.dumps(t) for t in traces(200)), encoding="utf-8")
    out = tmp_path / "to-score.jsonl"
    assert (
        main(
            [
                "online",
                "--source",
                str(source),
                "--state",
                str(tmp_path / "state"),
                "--out",
                str(out),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    written = [line for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(written) == payload["selected"]
    assert payload["selected"] < 200, "a stratified pass must not select everything"


def test_the_cli_reports_a_missing_source(capsys) -> None:
    from tooltrace.cli.main import main

    assert main(["online", "--source", "nope.jsonl", "--state", "state"]) != 0
    assert "no such file" in capsys.readouterr().err
