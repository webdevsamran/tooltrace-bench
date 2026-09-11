"""Distributed sweeps and bundle signing: both were built, neither was reachable.

`shard_work_items`, `merge_run_states`, `Coordinator`, `default_worker_inventory`
and `sign_bundle` all shipped in this repository with **no caller outside their
own tests**. A sweep could be sharded in principle and never in practice, and
`verify --signature` could check a cosign signature that nothing here could
produce.

That is this project's recurring defect, and the plan's own market analysis names
it: "the market is asking for this repo's dead code."

The two properties worth testing are about honesty rather than arithmetic. A
shard's numbers describe a *slice*, and the run has to say so or the number gets
read as the whole. And an unsigned bundle has to say it is unsigned -- a machine
without cosign is a normal machine, and a command that treated that as a build
failure would be switched off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.cli.main import main
from tooltrace.executors.experiment import shard_work_items

ROOT = Path(__file__).resolve().parents[1]


# --- sharding ---------------------------------------------------------------


def test_every_task_lands_in_exactly_one_shard() -> None:
    """A task in two shards is counted twice; a task in none is lost."""
    items = [(f"pack/task-{i}", 0) for i in range(43)]
    buckets = shard_work_items(items, 4)
    flat = [item for bucket in buckets for item in bucket]
    assert sorted(flat) == sorted(items)
    assert len(flat) == len(set(flat))


def test_sharding_is_deterministic() -> None:
    """Two machines must agree about which tasks are theirs without talking."""
    items = [(f"pack/task-{i}", 0) for i in range(20)]
    assert shard_work_items(items, 3) == shard_work_items(list(reversed(items)), 3)


def test_more_shards_than_tasks_leaves_some_empty() -> None:
    """A valid outcome, not an error: the CLI reports it and exits zero."""
    buckets = shard_work_items([("a/b", 0)], 4)
    assert sum(1 for bucket in buckets if not bucket) == 3


def test_zero_shards_is_refused() -> None:
    with pytest.raises(ValueError, match="shards must be"):
        shard_work_items([("a/b", 0)], 0)


# --- the CLI flag -----------------------------------------------------------


def test_a_shard_runs_a_strict_subset(tmp_path: Path, capsys) -> None:
    assert (
        main(["benchmark", "--agent", "scripted", "--runs", "1", "--shard", "0/6", "--json"]) == 0
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert 0 < len(payload["config"]["tasks"]) < 43


def test_the_run_says_it_is_a_slice(capsys) -> None:
    """A shard's rate is the rate of whichever tasks landed in that bucket.

    The sharding is deterministic, so that number is stable and wrong in the
    same way every time -- which is worse than noisy.
    """
    main(["benchmark", "--agent", "scripted", "--runs", "1", "--shard", "1/6", "--json"])
    assert "merge the shards before reading a rate" in capsys.readouterr().err


def test_only_one_note_is_printed_and_its_counts_match(capsys) -> None:
    """It printed "shard 0 of 4: 11 of 43" and then "running 43 of 43"."""
    main(["benchmark", "--agent", "scripted", "--runs", "1", "--shard", "0/6", "--json"])
    notes = [line for line in capsys.readouterr().err.splitlines() if line.startswith("note:")]
    assert len(notes) == 1, notes


@pytest.mark.parametrize("bad", ["3", "4/3", "-1/3", "0/0", "x/y"])
def test_a_malformed_shard_is_refused(bad: str) -> None:
    with pytest.raises(SystemExit):
        main(["benchmark", "--agent", "scripted", "--runs", "1", "--shard", bad, "--json"])


def test_the_shard_index_is_zero_based(capsys) -> None:
    """A CI matrix index and a list index both start at zero.

    A one-based flag would put an off-by-one in every user's workflow file.
    """
    assert (
        main(["benchmark", "--agent", "scripted", "--runs", "1", "--shard", "0/3", "--json"]) == 0
    )
    capsys.readouterr()
    with pytest.raises(SystemExit):
        main(["benchmark", "--agent", "scripted", "--runs", "1", "--shard", "3/3", "--json"])


# --- merging ----------------------------------------------------------------


def shard_into(tmp_path: Path, count: int, capsys) -> list[Path]:
    directories = []
    for index in range(count):
        out = tmp_path / f"shard{index}"
        main(
            [
                "benchmark",
                "--agent",
                "scripted",
                "--runs",
                "1",
                "--limit",
                "6",
                "--shard",
                f"{index}/{count}",
                "--out",
                str(out),
                "--json",
            ]
        )
        capsys.readouterr()
        directories.append(out)
    return directories


def test_merging_shards_recovers_the_whole_sweep(tmp_path: Path, capsys) -> None:
    directories = shard_into(tmp_path, 3, capsys)
    merged = tmp_path / "all"
    code = main(["merge", *[str(d) for d in directories], "--out", str(merged), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["conflicts"] == []
    assert len(list(merged.glob("*.tooltrace"))) == payload["bundles"]


def test_a_merge_reports_how_much_each_shard_contributed(tmp_path: Path, capsys) -> None:
    directories = shard_into(tmp_path, 2, capsys)
    main(["merge", *[str(d) for d in directories], "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["per_shard"]) == 2


def test_merging_a_missing_directory_is_refused(capsys) -> None:
    assert main(["merge", "no-such-shard-dir"]) != 0
    assert "not a directory" in capsys.readouterr().err


def test_merging_directories_with_no_bundles_is_refused(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["merge", str(empty)]) != 0
    assert "no .tooltrace bundles" in capsys.readouterr().err


# --- signing ----------------------------------------------------------------


def test_signing_says_plainly_when_the_tool_is_absent(capsys) -> None:
    """A machine without cosign is a normal machine.

    An unsigned bundle that says so is fine; one that silently pretends is not.
    """
    results = ROOT / "results"
    if not any(results.glob("*.tooltrace")):  # pragma: no cover - bundles ship
        pytest.skip("no published bundles in this checkout")
    code = main(
        ["sign", "--bundles", str(results), "--signer", "definitely-not-installed", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0, "an absent signing tool is not a build failure"
    assert payload["signed"] == 0
    assert "not installed" in payload["results"][0]["reason"]


def test_signing_never_claims_a_bundle_is_signed_when_it_is_not(capsys) -> None:
    results = ROOT / "results"
    if not any(results.glob("*.tooltrace")):  # pragma: no cover
        pytest.skip("no published bundles in this checkout")
    main(["sign", "--bundles", str(results), "--signer", "definitely-not-installed", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert all(row["signed"] is False for row in payload["results"])


def test_signing_a_missing_bundle_is_refused(capsys) -> None:
    assert main(["sign", "--bundles", "no-such-bundle-dir"]) != 0
    assert "no .tooltrace bundles" in capsys.readouterr().err


def test_no_custom_cryptography_is_implemented() -> None:
    """The rule the module states, checked rather than trusted.

    A project that rolled its own signature would be worse than one with no
    signatures at all, because the output would look the same.
    """
    source = (ROOT / "tooltrace" / "analysis" / "core.py").read_text(encoding="utf-8")
    for forbidden in ("import hmac", "import nacl", "from cryptography"):
        assert forbidden not in source, forbidden
    assert "sign-blob" in source, "signing must shell out to the external tool"


# --- the fleet --------------------------------------------------------------
#
# `Coordinator`, `default_worker_inventory`, `execute_experiment` and
# `merge_run_states` were the other four symbols with no caller outside their
# own tests: a complete file-queue fleet that could not be started. `tooltrace
# fleet` starts it.


def test_two_workers_never_claim_the_same_job(tmp_path: Path) -> None:
    """The whole correctness argument for a file queue.

    A claim is `os.replace` into the claiming worker's directory, which is
    atomic on every filesystem this runs on. If two workers could both win, the
    same run would be executed twice and counted twice.
    """
    from tooltrace.executors.experiment import Coordinator

    coordinator = Coordinator(tmp_path / "q")
    queued = {coordinator.enqueue({"task_id": f"p/t{i}", "repetition": 0}) for i in range(6)}

    seen: list[str] = []
    for worker in ("a", "b", "a", "b", "a", "b", "a"):
        job = coordinator.claim_next(worker)
        if job is not None:
            seen.append(str(job["job_id"]))

    assert sorted(seen) == sorted(queued)
    assert len(seen) == len(set(seen)), "a job was claimed twice"
    assert coordinator.pending_count() == 0


def test_enqueue_creates_one_job_per_task_and_repetition(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "fleet",
            "enqueue",
            "--queue",
            str(tmp_path / "q"),
            "--agent",
            "scripted",
            "--task",
            "file-editing/fix-config-typo,json-csv-transform/users-to-csv",
            "--runs",
            "3",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["jobs"] == 6
    assert payload["checksum"], "the manifest travels into every job unchecksummed otherwise"


def test_a_sweep_survives_the_round_trip_across_two_workers(tmp_path: Path, capsys) -> None:
    queue = tmp_path / "q"
    main(
        [
            "fleet",
            "enqueue",
            "--queue",
            str(queue),
            "--agent",
            "scripted",
            "--task",
            "file-editing/fix-config-typo,json-csv-transform/users-to-csv",
            "--runs",
            "2",
            "--json",
        ]
    )
    capsys.readouterr()

    main(["fleet", "work", "--queue", str(queue), "--worker-id", "w1", "--once", "--json"])
    first = json.loads(capsys.readouterr().out)
    main(["fleet", "work", "--queue", str(queue), "--worker-id", "w2", "--json"])
    second = json.loads(capsys.readouterr().out)
    assert first["claimed"] == 1
    assert second["claimed"] == 3

    assert main(["fleet", "collect", "--queue", str(queue), "--json"]) == 0
    merged = json.loads(capsys.readouterr().out)
    assert merged["completed"] == 4
    assert merged["failures"] == {}


def test_collect_refuses_when_two_workers_disagree(tmp_path: Path, capsys) -> None:
    """Not resolved, refused.

    Two workers reporting different results for the same (task, repetition)
    means the runs were not what they claim to be. Keeping one would hide that
    behind a clean-looking total.
    """
    from tooltrace.executors.experiment import RunState, idempotent_key

    states = tmp_path / "q" / "states"
    states.mkdir(parents=True)
    key = idempotent_key("exp", "p/t", 0)
    RunState(experiment_id="exp", completed={key: {"success": True}}).save(states / "w1.json")
    RunState(experiment_id="exp", completed={key: {"success": False}}).save(states / "w2.json")

    assert main(["fleet", "collect", "--queue", str(tmp_path / "q")]) != 0
    assert "conflicting results" in capsys.readouterr().err


def test_a_worker_missing_a_task_records_a_failure_and_the_rest_still_run(
    tmp_path: Path, capsys
) -> None:
    """One item's failure is isolated to that item."""
    from tooltrace.executors.experiment import Coordinator

    queue = tmp_path / "q"
    main(
        [
            "fleet",
            "enqueue",
            "--queue",
            str(queue),
            "--agent",
            "scripted",
            "--task",
            "file-editing/fix-config-typo",
            "--json",
        ]
    )
    capsys.readouterr()
    # A job for a pack this worker does not have. The manifest is reused so the
    # experiment id matches; only the task id is impossible.
    job = json.loads(next((queue / "jobs").glob("*.json")).read_text(encoding="utf-8"))
    Coordinator(queue).enqueue(
        {"experiment": job["experiment"], "task_id": "nowhere/nothing", "repetition": 0}
    )

    main(["fleet", "work", "--queue", str(queue), "--worker-id", "w1", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["completed"] == 1
    assert len(payload["failures"]) == 1
    assert "not installed" in next(iter(payload["failures"].values()))


def test_an_empty_queue_is_not_an_error(tmp_path: Path, capsys) -> None:
    assert main(["fleet", "work", "--queue", str(tmp_path / "q"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["claimed"] == 0


def test_status_reports_the_machine_it_is_run_on(tmp_path: Path, capsys) -> None:
    main(["fleet", "status", "--queue", str(tmp_path / "q"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["pending"] == 0
    assert payload["this_machine"]["worker_id"] == "local"


def test_no_gpu_and_not_checked_are_different_answers() -> None:
    """`WorkerInventory.gpu` defaulted to False and nothing ever set it.

    So every worker in a fleet reported "no GPU" whether or not it had one, and
    a hardcoded False reads as "checked, and there is none" --
    `tooltrace/telemetry/hardware.py` names this failure in its own docstring.
    """
    from tooltrace.executors.experiment import default_worker_inventory

    inventory = default_worker_inventory("local")
    assert inventory.gpu_detection in {"found", "none_found", "not_detectable"}
    assert inventory.gpu == bool(inventory.gpu_names)
    if inventory.gpu:
        assert inventory.gpu_detection == "found"


def test_a_second_pass_does_not_rerun_what_is_already_done(tmp_path: Path, capsys) -> None:
    """Resume: the state file is the record, and an interrupted fleet resumes."""
    from tooltrace.executors.experiment import RunState

    queue = tmp_path / "q"
    main(
        [
            "fleet",
            "enqueue",
            "--queue",
            str(queue),
            "--agent",
            "scripted",
            "--task",
            "file-editing/fix-config-typo",
            "--runs",
            "2",
            "--json",
        ]
    )
    capsys.readouterr()
    main(["fleet", "work", "--queue", str(queue), "--worker-id", "w1", "--json"])
    capsys.readouterr()
    state = RunState.load(queue / "states" / "w1.json")
    assert len(state.completed) == 2
    assert state.failures == {}
