"""The hook that says a prompt change invalidated your baselines.

A prompt is code, and it is the one kind that passes ruff, mypy and the whole
test suite while silently making yesterday's numbers incomparable to today's.
The agent did not get better or worse; it was asked a different question.

Two properties matter and both are tested here. It has to **notice**, or it is
decoration. And it has to **never block**, because a hook that refuses a
legitimate prompt improvement is removed within a week -- and then nobody hears
about the next one either.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.prompt_change_notice import findings, main

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """A real git repository, because the hook reads a real staged diff."""
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "mod.py").write_text('SYSTEM_PROMPT = "be helpful"\nOTHER = 1\n', encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "initial")
    monkeypatch.setattr("scripts.prompt_change_notice.ROOT", tmp_path)
    return tmp_path


def stage(repo: Path, text: str) -> Path:
    path = repo / "mod.py"
    path.write_text(text, encoding="utf-8")
    git(repo, "add", "mod.py")
    return path


# --- it notices -------------------------------------------------------------


def test_a_changed_system_prompt_is_reported(repo: Path) -> None:
    stage(repo, 'SYSTEM_PROMPT = "be extremely helpful"\nOTHER = 1\n')
    notes = findings([repo / "mod.py"])
    assert notes and "system prompt" in notes[0]


def test_a_changed_tool_description_is_reported(repo: Path) -> None:
    stage(repo, 'SYSTEM_PROMPT = "be helpful"\ndescription = "reads a file, carefully"\n')
    notes = findings([repo / "mod.py"])
    assert notes and "tool description" in notes[0]


def test_a_changed_parameter_schema_is_reported(repo: Path) -> None:
    stage(repo, 'SYSTEM_PROMPT = "be helpful"\nparameters = {"type": "object"}\n')
    notes = findings([repo / "mod.py"])
    assert notes and "argument schema" in notes[0]


def test_a_changed_history_window_is_reported(repo: Path) -> None:
    """How much conversation a model sees changes what it can do."""
    stage(repo, 'SYSTEM_PROMPT = "be helpful"\nHISTORY_TURNS = 40\n')
    assert findings([repo / "mod.py"])


# --- and does not cry wolf --------------------------------------------------


def test_an_unrelated_change_is_silent(repo: Path) -> None:
    stage(repo, 'SYSTEM_PROMPT = "be helpful"\nOTHER = 2\n')
    assert findings([repo / "mod.py"]) == []


def test_a_similarly_named_identifier_does_not_fire(repo: Path) -> None:
    """`descriptions_by_name` is not a tool description.

    A hook that fires on edits changing nothing a model sees is a hook that
    gets removed.
    """
    stage(repo, 'SYSTEM_PROMPT = "be helpful"\ndescriptions_by_name = {}\n')
    assert findings([repo / "mod.py"]) == []


def test_an_unstaged_file_produces_nothing(repo: Path) -> None:
    (repo / "mod.py").write_text('SYSTEM_PROMPT = "changed but not staged"\n', encoding="utf-8")
    assert findings([repo / "mod.py"]) == []


# --- and never blocks -------------------------------------------------------


def test_it_exits_zero_even_when_it_has_something_to_say(repo: Path, capsys) -> None:
    stage(repo, 'SYSTEM_PROMPT = "be extremely helpful"\n')
    assert main(["hook", str(repo / "mod.py")]) == 0
    out = capsys.readouterr().out
    assert "no longer comparable" in out
    assert "tooltrace baseline" in out, (
        "telling someone what is wrong without what to do is half a hook"
    )


def test_it_exits_zero_with_nothing_to_say(repo: Path, capsys) -> None:
    stage(repo, 'SYSTEM_PROMPT = "be helpful"\nOTHER = 3\n')
    assert main(["hook", str(repo / "mod.py")]) == 0
    assert capsys.readouterr().out == ""


def test_no_arguments_is_not_an_error() -> None:
    assert main(["hook"]) == 0


def test_a_path_outside_a_repository_is_survivable(tmp_path: Path, monkeypatch) -> None:
    """git failing must not fail the commit."""
    monkeypatch.setattr("scripts.prompt_change_notice.ROOT", tmp_path)
    assert main(["hook", str(tmp_path / "nothing.py")]) == 0


# --- the hook is actually installed -----------------------------------------


def test_the_hook_is_wired_into_pre_commit() -> None:
    """A hook nothing invokes is a script, which is this repository's oldest bug."""
    config = (Path(__file__).resolve().parents[1] / ".pre-commit-config.yaml").read_text(
        encoding="utf-8"
    )
    assert "prompt_change_notice.py" in config
    assert "id: prompt-changed" in config


def test_the_hook_watches_the_files_that_carry_a_prompt() -> None:
    config = (Path(__file__).resolve().parents[1] / ".pre-commit-config.yaml").read_text(
        encoding="utf-8"
    )
    assert "chat_base" in config, "the system prompt lives there"
    assert "tool_schemas" in config, "the catalogue renderer lives there"
    assert "tooltrace/tools/" in config, "tool descriptions live there"
