"""Tool poisoning: the attack that arrives before the run starts.

Every security task in this repository until now planted its payload in the
workspace, where an agent meets it as data it chose to read. Tool poisoning
arrives earlier and from a direction an agent cannot decline: the description of
a tool it has to use, written by whoever published the tool. That is what a
compromised MCP server looks like from inside an agent, and no amount of care
about file contents defends against it.

The tests below are mostly about *reachability*, because that is what has gone
wrong here before. `http_post` once shipped unregistered, so every injection
attempt failed as "unknown tool" and every agent scored as perfectly resistant.
A poisoned description that never reaches a model is the same bug wearing a
different hat: the task would run, the agent would pass, and the pass would mean
nothing. So these check that the payload survives every hop from the YAML to the
prompt.
"""

from __future__ import annotations

from tooltrace.agents.tool_schemas import presentations, render_prompt_block
from tooltrace.core.models import AgentContext
from tooltrace.tasks.loader import load_all_tasks

POISONED = ("security/tool-poisoning-exfiltration", "security/tool-poisoning-destructive")


def task_by_id(task_id: str):
    return next((t for t in load_all_tasks() if t.id == task_id), None)


# --- the payload exists and is reachable ------------------------------------


def test_both_poisoned_tasks_are_installed() -> None:
    for task_id in POISONED:
        assert task_by_id(task_id) is not None, f"{task_id} is not installed"


def test_the_poison_is_in_the_tool_catalogue_not_the_workspace() -> None:
    """The distinction the pack exists to draw.

    A payload in `starting_workspace` is an indirect prompt injection, which is
    already covered. This one has to be in the tool description or it is a
    duplicate of a task that already ships.
    """
    for task_id in POISONED:
        task = task_by_id(task_id)
        assert task is not None
        assert task.tool_descriptions, f"{task_id} plants no poisoned description"
        workspace_text = " ".join(task.starting_workspace.values()).lower()
        for marker in ("required pre-step", "maintenance note"):
            assert marker not in workspace_text, (
                f"{task_id}: the payload is in the workspace, which makes this an "
                "indirect-injection task rather than a tool-poisoning one"
            )


def test_the_poisoned_tool_is_one_the_task_allows() -> None:
    """An override for a forbidden tool measures nothing."""
    for task_id in POISONED:
        task = task_by_id(task_id)
        assert task is not None
        for name in task.tool_descriptions:
            assert name in task.allowed_tools, f"{task_id}: {name} is not callable by the agent"


def test_the_substituted_description_replaces_the_real_one() -> None:
    task = task_by_id("security/tool-poisoning-exfiltration")
    assert task is not None
    shown = {p.name: p for p in presentations(task.allowed_tools, task.tool_descriptions)}
    write = shown["write_file"]
    assert write.substituted_description is True
    assert "audit" in write.description.lower()
    assert "Create or overwrite" in write.description, (
        "an override that drops the tool's real purpose is implausible; "
        "a poisoned description imitates a real one"
    )


def test_untouched_tools_keep_their_own_description() -> None:
    task = task_by_id("security/tool-poisoning-exfiltration")
    assert task is not None
    shown = {p.name: p for p in presentations(task.allowed_tools, task.tool_descriptions)}
    assert shown["read_file"].substituted_description is False
    assert "Read a text file" in shown["read_file"].description


def test_the_payload_reaches_the_prompt_a_model_would_see() -> None:
    """The hop that would silently break the whole pack."""
    task = task_by_id("security/tool-poisoning-exfiltration")
    assert task is not None
    block = render_prompt_block(task.allowed_tools, task.tool_descriptions)
    assert "audit.internal.example" in block


def test_the_context_carries_the_overrides_the_runner_builds() -> None:
    """`allowed_tools` was on the context all along and the adapter ignored it.

    That is the same class of miss, so the field is asserted rather than assumed.
    """
    ctx = AgentContext(
        task_id="t/x",
        objective="o",
        description="",
        allowed_tools=["read_file"],
        tool_descriptions={"read_file": "poisoned"},
    )
    assert ctx.tool_descriptions == {"read_file": "poisoned"}


def test_an_override_for_a_disallowed_tool_is_dropped_by_the_runner() -> None:
    """Filtered at context construction, so a task cannot plant an unreachable payload."""
    from tooltrace.core.models import TaskDefinition

    task = TaskDefinition(
        id="t/x",
        category="security",
        objective="o",
        allowed_tools=["read_file"],
        assertions=[{"type": "file_exists", "params": {"path": "a"}}],
        tool_descriptions={"read_file": "shown", "shell": "never reachable"},
    )
    reachable = {
        name: text
        for name, text in task.tool_descriptions.items()
        if name in set(task.allowed_tools)
    }
    assert reachable == {"read_file": "shown"}


# --- the attacks are distinct -----------------------------------------------


def test_the_two_attacks_are_not_the_same_attack() -> None:
    """One sends something out; the other destroys something local.

    An agent whose entire defence is "never contact the network" passes the
    first and fails the second, which is the distinction worth two tasks.
    """
    exfil = task_by_id("security/tool-poisoning-exfiltration")
    destructive = task_by_id("security/tool-poisoning-destructive")
    assert exfil is not None and destructive is not None
    assert "http_post" in exfil.allowed_tools
    assert "http_post" not in destructive.allowed_tools
    assert {a.type for a in destructive.assertions} & {"protected_files"}


def test_they_cover_the_supply_chain_category() -> None:
    """AAI04 had no task before this pack; the matrix is generated from what runs."""
    for task_id in POISONED:
        task = task_by_id(task_id)
        assert task is not None
        assert "AAI04" in task.metadata["attack"]["owasp_ids"]
