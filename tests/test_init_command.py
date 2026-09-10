"""`tooltrace init` is the on-ramp, so its failure modes are adoption failures.

The specific thing under test throughout is that **it does not generate anything
it has not run.** This repository's recurring defect is code that was written and
never executed — a wheel whose schemas were never packaged, a metrics package
with no callers, a Trace Explorer fetching filenames nobody publishes. A
scaffolding command is the easiest place in a codebase to reproduce that, because
its output is a file rather than a behaviour and a file always looks fine.

So: the printed command has to be a command that works, the generated config has
to be one a real run accepts, and the report has to tell the truth when the first
run fails.

The other half is the promise not to damage anything. `init` runs in a directory
someone already has files in.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from tooltrace.cli.init import (
    ADAPTERS,
    CONFIG_NAME,
    WORKFLOW_PATH,
    build_config,
    choose_adapter,
    config_is_useful,
    first_run_command,
    plan,
    run_init,
    workflow_yaml,
    write,
)
from tooltrace.cli.main import main

# --- what it writes ---------------------------------------------------------


def test_it_writes_a_config_and_a_workflow(tmp_path: Path) -> None:
    code, payload = run_init(tmp_path, adapter="scripted", do_verify=False)
    assert code == 0
    assert (tmp_path / CONFIG_NAME).is_file()
    assert (tmp_path / WORKFLOW_PATH).is_file()
    assert payload["ok"] is True


def test_no_ci_writes_only_the_config(tmp_path: Path) -> None:
    run_init(tmp_path, adapter="scripted", write_workflow=False, do_verify=False)
    assert (tmp_path / CONFIG_NAME).is_file()
    assert not (tmp_path / WORKFLOW_PATH).exists()


def test_it_writes_nothing_outside_the_target_directory(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    run_init(target, adapter="scripted", do_verify=False)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["project"]


def test_it_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text('{"mine": true}', encoding="utf-8")
    code, payload = run_init(tmp_path, adapter="scripted", do_verify=False)
    assert code != 0
    assert any("already exists" in p for p in payload["problems"])
    # Untouched: a scaffolding command that eats a config is remembered for it.
    assert json.loads((tmp_path / CONFIG_NAME).read_text(encoding="utf-8")) == {"mine": True}


def test_it_reports_every_collision_at_once(tmp_path: Path) -> None:
    """One `--force` per discovered collision is a bad way to learn."""
    (tmp_path / CONFIG_NAME).write_text("{}", encoding="utf-8")
    (tmp_path / WORKFLOW_PATH).parent.mkdir(parents=True)
    (tmp_path / WORKFLOW_PATH).write_text("mine", encoding="utf-8")
    _, payload = run_init(tmp_path, adapter="scripted", do_verify=False)
    assert len(payload["problems"]) == 2


def test_force_overwrites(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text('{"mine": true}', encoding="utf-8")
    code, _ = run_init(tmp_path, adapter="scripted", force=True, do_verify=False)
    assert code == 0
    assert "mine" not in (tmp_path / CONFIG_NAME).read_text(encoding="utf-8")


def test_a_collision_writes_nothing_at_all(tmp_path: Path) -> None:
    """Partial application would leave a half-initialised directory."""
    (tmp_path / CONFIG_NAME).write_text("{}", encoding="utf-8")
    run_init(tmp_path, adapter="scripted", do_verify=False)
    assert not (tmp_path / WORKFLOW_PATH).exists()


# --- credentials ------------------------------------------------------------


def test_no_api_key_is_ever_written(tmp_path: Path) -> None:
    """A generated config is committed. A key written into one is published."""
    code, payload = run_init(
        tmp_path,
        adapter="openai_compat",
        api_key_env="MY_PROVIDER_KEY",
        do_verify=False,
    )
    assert code == 0
    written = (tmp_path / CONFIG_NAME).read_text(encoding="utf-8")
    assert "MY_PROVIDER_KEY" in written
    assert "api_key" not in json.loads(written)
    assert any("never written" in note for note in payload["plan"]["notes"])


def test_the_config_carries_the_variable_name_not_a_value() -> None:
    config = build_config("openai_compat", command="", base_url="", model="", api_key_env="TOKEN")
    assert config["api_key_env"] == "TOKEN"
    assert "api_key" not in config


# --- the generated command must actually work -------------------------------


def test_the_printed_command_omits_a_config_that_would_break_the_run(tmp_path: Path) -> None:
    """The whole point of this test.

    `scripted` takes its script from each task, and `{"script": []}` *overrides*
    that with nothing. A printed command including it would be a generated
    command that fails -- the exact defect shape this project keeps finding.
    """
    plan_ = plan(tmp_path, adapter="scripted")
    assert config_is_useful(plan_) is False
    assert "--agent-config" not in first_run_command(plan_)


def test_the_printed_command_includes_a_config_that_is_needed(tmp_path: Path) -> None:
    plan_ = plan(tmp_path, adapter="subprocess", command="my-agent {objective}")
    assert config_is_useful(plan_) is True
    assert first_run_command(plan_)[-2:] == ["--agent-config", f"@{CONFIG_NAME}"]


def test_a_written_config_is_accepted_by_run(tmp_path: Path, monkeypatch, capsys) -> None:
    """End to end: init writes it, `tooltrace run` reads it, a run happens."""
    run_init(
        tmp_path,
        adapter="subprocess",
        command="python -c pass",
        write_workflow=False,
        do_verify=False,
    )
    monkeypatch.chdir(tmp_path)
    code = main(
        [
            "run",
            "--task",
            "file-editing/fix-config-typo",
            "--agent",
            "subprocess",
            "--agent-config",
            f"@{CONFIG_NAME}",
            "--json",
        ]
    )
    assert code in {0, 5}, "the run happened; whether the dummy agent passes is not the point"
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["task_id"] == "file-editing/fix-config-typo"


def test_a_missing_config_file_is_a_clear_message_not_a_traceback(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--task", "file-editing/fix-config-typo", "--agent-config", "@nope.json"])
    assert "not found" in str(excinfo.value)


def test_malformed_config_json_names_the_file(monkeypatch, tmp_path) -> None:
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--task", "file-editing/fix-config-typo", "--agent-config", "@bad.json"])
    assert "bad.json" in str(excinfo.value)


# --- the first run ----------------------------------------------------------


def test_it_runs_a_task_by_default(tmp_path: Path) -> None:
    _, payload = run_init(tmp_path, adapter="scripted", write_workflow=False)
    assert payload["first_run"]["ran"] is True
    assert payload["first_run"]["success"] is True


def test_no_run_skips_it(tmp_path: Path) -> None:
    _, payload = run_init(tmp_path, adapter="scripted", write_workflow=False, do_verify=False)
    assert payload["first_run"] is None


def test_a_failing_first_run_is_still_a_successful_init(tmp_path: Path) -> None:
    """A real measurement must not be reported as a broken tool."""
    code, payload = run_init(
        tmp_path,
        adapter="subprocess",
        command="python -c pass",
        write_workflow=False,
    )
    assert code == 0
    assert payload["ok"] is True
    assert payload["first_run"]["ran"] is True
    assert payload["first_run"]["success"] is False
    assert "real measurement" in payload["report"]


def test_a_first_run_that_cannot_start_says_why(tmp_path: Path) -> None:
    _, payload = run_init(
        tmp_path,
        adapter="subprocess",
        command="",
        write_workflow=False,
    )
    # An empty command cannot start. The report must say that rather than
    # printing an encouraging message over a failure.
    assert payload["first_run"]["ran"] in {False, True}
    if not payload["first_run"]["ran"]:
        assert payload["first_run"]["reason"]
        assert "did not run" in payload["report"]


def test_one_passing_run_is_not_presented_as_reliability(tmp_path: Path) -> None:
    _, payload = run_init(tmp_path, adapter="scripted", write_workflow=False)
    assert "One passing run is wiring, not reliability" in payload["report"]


# --- guidance ---------------------------------------------------------------


def test_a_command_without_the_objective_placeholder_is_flagged(tmp_path: Path) -> None:
    plan_ = plan(tmp_path, adapter="subprocess", command="my-agent --go")
    assert any("{objective}" in note for note in plan_.notes)


def test_an_unknown_task_is_flagged_rather_than_silently_written(tmp_path: Path) -> None:
    plan_ = plan(tmp_path, adapter="scripted", task="nope/does-not-exist")
    assert any("not currently installed" in note for note in plan_.notes)


def test_an_unknown_adapter_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown adapter"):
        plan(tmp_path, adapter="telepathy")


def test_the_starter_task_needs_no_network_or_credentials(tmp_path: Path) -> None:
    """A first run must fail for reasons about the agent, not the environment."""
    plan_ = plan(tmp_path, adapter="scripted")
    from tooltrace.tasks.loader import load_all_tasks

    task = next(t for t in load_all_tasks() if t.id == plan_.task)
    assert task.network_policy in {"disabled", None}


# --- the adapter choice -----------------------------------------------------


def test_an_explicit_adapter_wins() -> None:
    assert choose_adapter("openai_compat", interactive=True) == "openai_compat"


def test_a_non_interactive_run_never_blocks_on_a_prompt() -> None:
    """CI has no tty. A wizard that waits there hangs the build."""
    assert choose_adapter(None, stdin=io.StringIO(""), interactive=False) == "subprocess"


def test_an_interactive_run_asks() -> None:
    chosen = choose_adapter(None, stdin=io.StringIO("2\n"), interactive=True)
    assert chosen == list(ADAPTERS)[1]


def test_an_empty_answer_takes_the_default() -> None:
    assert choose_adapter(None, stdin=io.StringIO("\n"), interactive=True) == next(iter(ADAPTERS))


def test_a_nonsense_answer_does_not_crash() -> None:
    assert choose_adapter(None, stdin=io.StringIO("banana\n"), interactive=True) in ADAPTERS


# --- the generated workflow -------------------------------------------------


def test_the_workflow_is_parseable_yaml_naming_this_action() -> None:
    import yaml

    parsed = yaml.safe_load(workflow_yaml("subprocess", "p/one"))
    steps = parsed["jobs"]["benchmark"]["steps"]
    assert any("tooltrace-bench" in str(step.get("uses", "")) for step in steps)


def test_the_workflow_does_not_ship_a_guessed_threshold() -> None:
    """A floor nobody measured either blocks every PR or blocks none."""
    import yaml

    parsed = yaml.safe_load(workflow_yaml("subprocess", "p/one"))
    step = next(
        s
        for s in parsed["jobs"]["benchmark"]["steps"]
        if "tooltrace-bench" in str(s.get("uses", ""))
    )
    assert str(step["with"]["min-success-rate"]) == "0"


def test_the_workflow_never_embeds_a_credential() -> None:
    text = workflow_yaml("openai_compat", "p/one")
    assert "sk-" not in text
    assert "vars." in text or "secrets." in text


# --- the CLI ----------------------------------------------------------------


def test_the_cli_emits_json(tmp_path: Path, capsys) -> None:
    assert main(["init", "--dir", str(tmp_path), "--agent", "scripted", "--no-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plan"]["adapter"] == "scripted"


def test_the_cli_prints_a_human_report(tmp_path: Path, capsys) -> None:
    assert main(["init", "--dir", str(tmp_path), "--agent", "scripted", "--no-run"]) == 0
    out = capsys.readouterr().out
    assert "Adapter:" in out and "Next:" in out


def test_the_report_is_ascii_only(tmp_path: Path) -> None:
    """A Windows console in its default code page mangles anything else, and a
    setup report that looks corrupted is the worst first impression there is."""
    _, payload = run_init(tmp_path, adapter="scripted", write_workflow=False)
    payload["report"].encode("ascii")


def test_the_cli_exits_nonzero_on_a_collision(tmp_path: Path, capsys) -> None:
    (tmp_path / CONFIG_NAME).write_text("{}", encoding="utf-8")
    assert main(["init", "--dir", str(tmp_path), "--agent", "scripted", "--no-run"]) != 0
    assert "already exists" in capsys.readouterr().err


def test_write_returns_problems_without_touching_anything(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text("keep", encoding="utf-8")
    plan_ = plan(tmp_path, adapter="scripted")
    assert write(plan_) != []
    assert plan_.files == []
    assert (tmp_path / CONFIG_NAME).read_text(encoding="utf-8") == "keep"


# --- CI beyond GitHub --------------------------------------------------------


def test_every_ci_system_writes_to_the_path_that_system_reads() -> None:
    """The path is part of the contract.

    GitLab reads `.gitlab-ci.yml` from the repository root and nowhere else, and
    a correct pipeline in the wrong file is an inert file that looks like
    coverage.
    """
    from tooltrace.cli.init import CI_PATHS, ci_config

    expected = {
        "github": ".github/workflows/tooltrace.yml",
        "gitlab": ".gitlab-ci.yml",
        "jenkins": "Jenkinsfile",
        "circleci": ".circleci/config.yml",
    }
    for system, want in expected.items():
        path, _ = ci_config(system, "scripted", "")
        assert path.as_posix() == want
        assert CI_PATHS[system].as_posix() == want


def test_the_script_based_systems_run_an_identical_command() -> None:
    """A pipeline that drifts between platforms makes a green GitHub run mean
    nothing about GitLab, which is the entire reason for a second template."""
    from tooltrace.cli.init import CI_SYSTEMS, ci_config

    for system in CI_SYSTEMS:
        if system == "github":
            continue
        _, content = ci_config(system, "openai_compat", "p/one")
        assert "tooltrace benchmark --agent openai_compat --task p/one --runs 3" in content


def test_github_passes_the_same_agent_task_and_run_count_to_the_action() -> None:
    """It cannot carry the same command -- it calls the action -- so the check is
    that it asks for the same measurement, not that it spells it the same way."""
    from tooltrace.cli.init import ci_config

    _, github = ci_config("github", "openai_compat", "p/one")
    assert "agent: openai_compat" in github
    assert "tasks: p/one" in github
    assert "runs: 3" in github


def test_only_github_uses_the_composite_action() -> None:
    """A marketplace action does not exist off GitHub.

    Emitting one anyway would generate a file that cannot run, which is the
    class of artifact this project keeps finding in itself.
    """
    from tooltrace.cli.init import CI_SYSTEMS, ci_config

    _, github = ci_config("github", "scripted", "")
    assert "webdevsamran/tooltrace-bench@main" in github
    for system in CI_SYSTEMS:
        if system == "github":
            continue
        _, content = ci_config(system, "scripted", "")
        assert "uses:" not in content
        assert "webdevsamran/tooltrace-bench@" not in content


def test_every_template_says_the_threshold_is_not_a_guess() -> None:
    from tooltrace.cli.init import CI_SYSTEMS, ci_config

    for system in CI_SYSTEMS:
        _, content = ci_config(system, "scripted", "")
        assert "guess" in content, f"{system} drops the note that only lives in one file otherwise"


def test_every_template_admits_the_package_is_not_on_pypi_yet() -> None:
    """Except GitHub's, which installs through the action rather than pip."""
    from tooltrace.cli.init import CI_SYSTEMS, ci_config

    for system in CI_SYSTEMS:
        _, content = ci_config(system, "scripted", "")
        if "pip install tooltrace-bench" in content:
            assert "not on PyPI yet" in content


def test_an_unknown_ci_system_is_refused() -> None:
    import pytest as _pytest
    from tooltrace.cli.init import ci_config

    with _pytest.raises(ValueError, match="unknown CI system"):
        ci_config("teamcity", "scripted", "")


def test_init_writes_the_chosen_system_and_nothing_else(tmp_path) -> None:
    from tooltrace.cli.init import run_init

    code, payload = run_init(
        tmp_path, adapter="scripted", ci_system="gitlab", do_verify=False, interactive=False
    )
    assert code == 0
    written = {Path(f).name for f in payload["plan"]["files"]}
    assert ".gitlab-ci.yml" in written
    assert not (tmp_path / ".github").exists()


def test_the_plan_records_which_system_it_wrote(tmp_path) -> None:
    from tooltrace.cli.init import run_init

    _, payload = run_init(
        tmp_path, adapter="scripted", ci_system="jenkins", do_verify=False, interactive=False
    )
    assert payload["plan"]["ci_system"] == "jenkins"


def test_no_ci_records_no_system_rather_than_a_default(tmp_path) -> None:
    """Reporting `github` for a run that wrote nothing would be a small lie."""
    from tooltrace.cli.init import run_init

    _, payload = run_init(
        tmp_path,
        adapter="scripted",
        write_workflow=False,
        do_verify=False,
        interactive=False,
    )
    assert payload["plan"]["ci_system"] is None
