"""Ablation: which tools was the agent actually relying on?

Two agents can score identically and be doing entirely different things -- one
has a plan and adapts when a tool is missing, the other walks a path it has
walked before. Every other metric in this project reads a run in which
everything worked, so nothing else tells them apart.

Three verdicts, and the interesting ones are the two that are *not* a defect:

- **`redundant`** does not mean useless. The agent found another way this time,
  which may be a worse one.
- **`unused`** on an ordinary task usually means the task declares more than it
  needs. On a *security* task it usually means the opposite: the tool is there
  because the attack needs it, and a resistant agent never touching it is the
  pass condition. Removing it would make the attack unreachable and every agent
  would look perfectly safe -- a bug this repository has actually shipped.
"""

from __future__ import annotations

from typing import Any

from tooltrace.analysis.counterfactual import (
    LOAD_BEARING,
    REDUNDANT,
    UNUSED,
    ablate,
    render_markdown,
)
from tooltrace.core.models import TaskDefinition


def task(task_id: str = "p/one", tools: list[str] | None = None) -> TaskDefinition:
    return TaskDefinition(
        id=task_id,
        category="general",
        objective="do it",
        allowed_tools=tools or ["read_file", "write_file", "search_text"],
        assertions=[{"type": "file_exists", "params": {"path": "a"}}],
    )


class FakeEvent:
    def __init__(self, tool: str) -> None:
        self.type = "tool_request"
        self.payload = {"tool": tool}


class FakeResult:
    def __init__(self, success: bool) -> None:
        self.success = success


class FakeRunner:
    """Passes unless one of `breaks_without` is missing from `allowed_tools`."""

    def __init__(self, *, calls: list[str], breaks_without: set[str]) -> None:
        self.calls = calls
        self.breaks_without = breaks_without
        self.seen: list[list[str]] = []

    def run(
        self,
        task_: Any,
        agent_name: str,
        agent_config: dict[str, object] | None = None,
        run_id: str | None = None,
    ) -> tuple[Any, list[Any], str]:
        allowed = list(task_.allowed_tools)
        self.seen.append(allowed)
        missing = self.breaks_without - set(allowed)
        events = [FakeEvent(tool) for tool in self.calls if tool in allowed]
        return FakeResult(not missing), events, ""


# --- the three verdicts -----------------------------------------------------


def test_a_tool_whose_removal_breaks_the_task_is_load_bearing() -> None:
    runner = FakeRunner(calls=["read_file", "write_file"], breaks_without={"write_file"})
    report = ablate(task(), "fake", None, runner)
    verdicts = {a["tool"]: a["verdict"] for a in report["arms"]}
    assert verdicts["write_file"] == LOAD_BEARING
    assert report["load_bearing"] == ["write_file"]


def test_a_tool_the_agent_can_work_around_is_redundant_not_useless() -> None:
    runner = FakeRunner(calls=["read_file", "write_file"], breaks_without={"write_file"})
    report = ablate(task(), "fake", None, runner)
    row = next(a for a in report["arms"] if a["tool"] == "read_file")
    assert row["verdict"] == REDUNDANT
    assert "not the same as useless" in row["note"]


def test_a_tool_never_called_is_unused_rather_than_redundant() -> None:
    """Nothing was removed, so nothing was learned about it."""
    runner = FakeRunner(calls=["read_file", "write_file"], breaks_without={"write_file"})
    row = next(
        a for a in ablate(task(), "fake", None, runner)["arms"] if a["tool"] == "search_text"
    )
    assert row["verdict"] == UNUSED
    assert row["passes"] is None, "a verdict of n/a must not be reported as zero passes"


def test_an_unused_tool_is_not_ablated_at_all() -> None:
    """Running an arm that removes a tool nobody called would burn a run to
    learn nothing."""
    runner = FakeRunner(calls=["read_file"], breaks_without=set())
    ablate(task(), "fake", None, runner)
    # baseline + one arm each for read_file and write_file... write_file was
    # never called, so only read_file is ablated.
    assert len(runner.seen) == 2


# --- the security nuance ----------------------------------------------------


def test_an_uncalled_tool_on_a_security_task_is_explained_differently() -> None:
    """It is usually the attack surface, not a surplus declaration.

    Removing it would make the attack unreachable and every agent would score as
    perfectly resistant, which is a bug this repository has shipped.
    """
    runner = FakeRunner(calls=["read_file"], breaks_without=set())
    report = ablate(task("security/poisoned"), "fake", None, runner)
    row = next(a for a in report["arms"] if a["tool"] == "write_file")
    assert "the attack needs it" in row["note"]


def test_an_uncalled_tool_on_an_ordinary_task_reads_as_over_declaration() -> None:
    runner = FakeRunner(calls=["read_file"], breaks_without=set())
    row = next(a for a in ablate(task(), "fake", None, runner)["arms"] if a["tool"] == "write_file")
    assert "declares a tool it does not need" in row["note"]


# --- refusals ---------------------------------------------------------------


def test_a_failing_baseline_is_not_ablated() -> None:
    """Every arm would fail and every tool would read as load-bearing."""
    runner = FakeRunner(calls=[], breaks_without={"read_file", "nonexistent"})
    report = ablate(task(), "fake", None, runner)
    assert report["measurable"] is False
    assert "measures nothing" in report["reason"]
    assert report["arms"] == []


def test_the_report_says_an_ablation_is_not_a_clean_intervention() -> None:
    """Removing a tool also removes its line from the catalogue the model reads."""
    runner = FakeRunner(calls=["read_file"], breaks_without=set())
    assert (
        "told something different rather than merely given less"
        in (ablate(task(), "fake", None, runner)["caveat"])
    )


def test_one_run_per_arm_is_flagged_as_a_draw() -> None:
    runner = FakeRunner(calls=["read_file"], breaks_without=set())
    report = ablate(task(), "fake", None, runner)
    assert report["sample_is_small"] is True
    assert "a draw rather than a property" in report["statement"]


def test_five_runs_per_arm_is_no_longer_flagged() -> None:
    runner = FakeRunner(calls=["read_file"], breaks_without=set())
    report = ablate(task(), "fake", None, runner, runs_per_arm=5)
    assert report["sample_is_small"] is False


# --- the ablation does not leak ---------------------------------------------


def test_the_original_task_is_never_mutated() -> None:
    """Mutating the loaded task would leak the ablation into every later run in
    the process, including the next task's baseline."""
    original = task()
    before = list(original.allowed_tools)
    runner = FakeRunner(calls=["read_file", "write_file"], breaks_without=set())
    ablate(original, "fake", None, runner)
    assert original.allowed_tools == before


def test_each_arm_removes_exactly_one_tool() -> None:
    runner = FakeRunner(calls=["read_file", "write_file"], breaks_without=set())
    ablate(task(), "fake", None, runner)
    for allowed in runner.seen[1:]:
        assert len(allowed) == 2, "an arm must differ from the baseline by one tool"


# --- rendering --------------------------------------------------------------


def test_the_table_renders_an_unmeasurable_report_as_a_sentence() -> None:
    runner = FakeRunner(calls=[], breaks_without={"nonexistent"})
    rendered = render_markdown(ablate(task(), "fake", None, runner))
    assert "Not measurable" in rendered


def test_the_rendered_table_carries_the_caveat() -> None:
    runner = FakeRunner(calls=["read_file"], breaks_without=set())
    rendered = render_markdown(ablate(task(), "fake", None, runner))
    assert "not a clean" in rendered or "told something different" in rendered


# --- end to end on a real task ----------------------------------------------


def test_a_real_task_ablates_against_the_real_runner() -> None:
    """The fakes above test the logic; this proves it drives the actual runner."""
    from tooltrace.runners.runner import TaskRunner
    from tooltrace.tasks.loader import load_all_tasks

    real = next(t for t in load_all_tasks() if t.id == "file-editing/fix-config-typo")
    script = real.metadata.get("scripted_script")
    assert script, "this task must ship a reference script"
    report = ablate(real, "scripted", {"script": script}, TaskRunner())
    assert report["measurable"] is True
    assert report["load_bearing"], "some tool in a real task has to be load-bearing"
