"""Importing a task from another benchmark, and saying what did not come across.

Every one of these benchmarks measures something real and none of them measures
what this project measures, so a converted task is **not** the original task. A
silently converted SWE-bench instance that scores 0.4 here tells a reader nothing
unless they know which half of the original grading survived.

So the tests are mostly about the loss report: every draft carries what its
conversion dropped, in its own metadata rather than in a message printed once,
and the conversions that lose the most are the ones whose output looks most
complete.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.tasks.importers import (
    AGENTBENCH,
    BFCL,
    FORMATS,
    SWE_BENCH,
    TAU_BENCH,
    convert,
    from_agentbench,
    from_bfcl,
    from_swe_bench,
    from_tau_bench,
)

SWE_RECORD = {
    "instance_id": "django__django-11099",
    "repo": "django/django",
    "base_commit": "d26b2424437dabeeca94d7900b37d2df4410da0c",
    "problem_statement": "UsernameValidator allows trailing newline in usernames",
    "test_cmd": "./tests/runtests.py",
}

BFCL_RECORD = {
    "id": "simple_42",
    "question": [{"role": "user", "content": "What is the weather in Paris?"}],
    "function": [{"name": "get_weather", "parameters": {"city": {"type": "string"}}}],
    "ground_truth": [{"get_weather": {"city": "Paris"}}],
}

TAU_RECORD = {
    "id": "retail_7",
    "instruction": "Cancel order #12345 and refund to the original payment method.",
    "outputs": ["cancelled"],
}


# --- every output is a draft ------------------------------------------------


@pytest.mark.parametrize(
    ("importer", "record"),
    [
        (from_swe_bench, SWE_RECORD),
        (from_bfcl, BFCL_RECORD),
        (from_tau_bench, TAU_RECORD),
        (from_agentbench, {"environment": "os", "id": "1", "expected": "42"}),
    ],
)
def test_every_conversion_is_marked_a_draft(importer, record) -> None:
    task = importer(record)
    assert task["metadata"]["is_draft"] is True
    assert task["metadata"]["todo"], "a draft with no TODO is a task somebody will just run"


@pytest.mark.parametrize(
    ("importer", "record"),
    [
        (from_swe_bench, SWE_RECORD),
        (from_bfcl, BFCL_RECORD),
        (from_tau_bench, TAU_RECORD),
    ],
)
def test_every_conversion_records_what_it_lost(importer, record) -> None:
    """The loss list is the feature; a conversion with none is claiming
    equivalence it does not have."""
    task = importer(record)
    assert task["metadata"]["conversion_losses"]
    assert task["metadata"]["imported_from"] in FORMATS


# --- SWE-bench --------------------------------------------------------------


def test_swe_bench_keeps_the_oracle_that_translates() -> None:
    """Hidden tests passing is the same shape as `tests_pass`."""
    task = from_swe_bench(SWE_RECORD)
    assert task["assertions"][0]["type"] == "tests_pass"


def test_swe_bench_says_the_repository_is_not_fetched() -> None:
    """The single most important thing about the conversion.

    A user who ran this without knowing would score an agent on an empty
    workspace and conclude the agent could not fix Django.
    """
    losses = " ".join(from_swe_bench(SWE_RECORD)["metadata"]["conversion_losses"])
    assert "not fetched" in losses
    assert "django/django@" in losses


def test_swe_bench_names_the_test_command_the_instance_uses() -> None:
    todos = " ".join(from_swe_bench(SWE_RECORD)["metadata"]["todo"])
    assert "./tests/runtests.py" in todos


def test_swe_bench_admits_the_pass_split_is_collapsed() -> None:
    """FAIL_TO_PASS and PASS_TO_PASS are different questions and one ratio
    cannot express a regression in the second."""
    losses = " ".join(from_swe_bench(SWE_RECORD)["metadata"]["conversion_losses"])
    assert "PASS_TO_PASS" in losses


# --- BFCL -------------------------------------------------------------------


def test_bfcl_becomes_a_structural_call_match() -> None:
    """Its grading is exactly what `tool_call_match` does."""
    task = from_bfcl(BFCL_RECORD)
    assertion = task["assertions"][0]
    assert assertion["type"] == "tool_call_match"
    assert assertion["params"]["expected"][0]["tool"] == "get_weather"
    assert assertion["params"]["expected"][0]["args"] == ["city"]


def test_bfcl_carries_the_prompt_from_a_conversation() -> None:
    assert "weather in Paris" in from_bfcl(BFCL_RECORD)["objective"]


def test_bfcl_says_it_is_trajectory_only() -> None:
    """BFCL executes nothing, so there is no end state to assert on."""
    losses = " ".join(from_bfcl(BFCL_RECORD)["metadata"]["conversion_losses"])
    assert "No workspace" in losses


def test_bfcl_warns_that_its_functions_are_not_registered_here() -> None:
    """Otherwise every call fails as an unknown tool and the agent looks broken."""
    losses = " ".join(from_bfcl(BFCL_RECORD)["metadata"]["conversion_losses"])
    assert "unknown" in losses
    assert from_bfcl(BFCL_RECORD)["allowed_tools"] == ["get_weather"]


def test_bfcl_with_no_ground_truth_produces_no_assertion_rather_than_a_vacuous_one() -> None:
    task = from_bfcl({"id": "x", "question": "hello"})
    assert task["assertions"] == []


# --- tau-bench --------------------------------------------------------------


def test_tau_bench_says_the_simulated_user_is_gone() -> None:
    """The converted task is strictly easier than the original, and that has to
    be said or a comparison across the two is meaningless."""
    losses = " ".join(from_tau_bench(TAU_RECORD)["metadata"]["conversion_losses"])
    assert "simulated user is gone" in losses
    assert "strictly easier" in losses


def test_tau_bench_points_at_the_machinery_that_would_restore_it() -> None:
    todos = " ".join(from_tau_bench(TAU_RECORD)["metadata"]["todo"])
    assert "adversarial-user" in todos


# --- AgentBench refuses rather than approximating ---------------------------


def test_an_environment_with_a_model_judge_is_refused() -> None:
    """An approximated oracle is a task that scores something nobody chose."""
    refusal = from_agentbench({"environment": "alfworld", "id": "3"})
    assert refusal["convertible"] is False
    assert "model judge" in refusal["reason"]


def test_the_os_environment_converts() -> None:
    task = from_agentbench({"environment": "os", "id": "3", "expected": "42"})
    assert task["metadata"]["imported_from"] == AGENTBENCH
    assert task["assertions"][0]["params"]["text"] == "42"


def test_an_environment_that_is_not_declared_is_refused_rather_than_guessed() -> None:
    assert from_agentbench({"id": "3"})["convertible"] is False


# --- batches ----------------------------------------------------------------


def test_refusals_are_reported_alongside_the_drafts() -> None:
    """A refused record that vanished from the output would look like a record
    that was never there."""
    report = convert(
        AGENTBENCH,
        [{"environment": "os", "id": "1", "expected": "a"}, {"environment": "alfworld", "id": "2"}],
    )
    assert len(report["tasks"]) == 1
    assert len(report["refused"]) == 1
    assert "refused as unconvertible" in report["statement"]


def test_the_batch_statement_says_every_task_is_a_draft() -> None:
    report = convert(SWE_BENCH, [SWE_RECORD])
    assert report["all_drafts"] is True
    assert "**Every one is a draft.**" in report["statement"]


def test_an_unknown_source_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown source"):
        convert("mmlu", [])


def test_task_ids_are_namespaced_and_valid() -> None:
    """They have to satisfy the task-id pattern or nothing can load them."""
    import re

    pattern = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
    for source, record in (
        (SWE_BENCH, SWE_RECORD),
        (BFCL, BFCL_RECORD),
        (TAU_BENCH, TAU_RECORD),
    ):
        task = convert(source, [record])["tasks"][0]
        assert pattern.match(task["id"]), task["id"]


# --- the CLI ----------------------------------------------------------------


def test_the_cli_writes_one_yaml_per_draft(tmp_path: Path, capsys) -> None:
    import yaml
    from tooltrace.cli.main import main

    source = tmp_path / "records.jsonl"
    source.write_text(json.dumps(SWE_RECORD), encoding="utf-8")
    out = tmp_path / "drafts"
    assert (
        main(
            [
                "import",
                "--format",
                "swe-bench",
                "--source",
                str(source),
                "--out",
                str(out),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()

    written = sorted(out.glob("*.yaml"))
    assert len(written) == 1
    loaded = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    assert loaded["metadata"]["is_draft"] is True


def test_the_cli_accepts_a_json_array_as_well_as_jsonl(tmp_path: Path, capsys) -> None:
    from tooltrace.cli.main import main

    source = tmp_path / "records.json"
    source.write_text(json.dumps([SWE_RECORD, SWE_RECORD]), encoding="utf-8")
    assert main(["import", "--format", "swe-bench", "--source", str(source), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["records"] == 2


def test_the_cli_reports_a_missing_file(capsys) -> None:
    from tooltrace.cli.main import main

    assert main(["import", "--format", "bfcl", "--source", "nope.json"]) != 0
    assert "no such file" in capsys.readouterr().err


def test_the_cli_reports_unparseable_input(tmp_path: Path, capsys) -> None:
    from tooltrace.cli.main import main

    source = tmp_path / "bad.json"
    source.write_text("{not json", encoding="utf-8")
    assert main(["import", "--format", "bfcl", "--source", str(source)]) != 0
    assert "not JSON" in capsys.readouterr().err
