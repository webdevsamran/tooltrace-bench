"""`tooltrace init` — from "I have an agent" to a reliability number.

The distance between installing this project and learning something about your
own agent was, until now: read the adapter docs, work out that `subprocess`
takes a `command` with an `{objective}` placeholder, hand-write JSON, quote it
correctly for your shell, guess a task id, and run it. Every one of those steps
is a place to give up, and none of them teaches anything about your agent.

So this command does the whole path: it works out what is installed, writes a
config for the adapter that matches how your agent is invoked, and then — by
default — **runs one real task with it** and prints the outcome. A scaffold that
stops at writing files leaves the user to discover their config is wrong on
their own time; running it once is the difference between a template and an
on-ramp.

Three deliberate constraints:

- **Nothing is written outside the target directory**, and nothing existing is
  overwritten without `--force`. A scaffolding command that clobbers a config is
  remembered for that and nothing else.
- **No credential is ever written to a file.** `openai_compat` gets the *name*
  of an environment variable, never a key. A generated file lands in git.
- **It is honest when the first run fails.** A failed first run is information
  about the agent or the command, and the report says which; printing a cheerful
  "you're all set" over a failure would be the worst thing this command could do.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tooltrace.core.versions import FRAMEWORK_VERSION

CONFIG_NAME = "tooltrace.config.json"
WORKFLOW_PATH = Path(".github") / "workflows" / "tooltrace.yml"

#: What the generated config means, per adapter. Kept here rather than in the
#: prompt text so the JSON payload and the printed guidance cannot drift.
ADAPTERS: dict[str, str] = {
    "subprocess": "any agent you can invoke as a command line",
    "openai_compat": "an OpenAI-compatible chat endpoint (including local servers)",
    "scripted": "a fixed script of tool calls - the deterministic demo, no model",
}

DEFAULT_COMMAND = "my-agent --task {objective}"


@dataclass
class InitPlan:
    """What `init` decided to do, before it does any of it."""

    directory: Path
    adapter: str
    agent_config: dict[str, Any]
    task: str
    write_workflow: bool
    files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "directory": str(self.directory),
            "adapter": self.adapter,
            "agent_config": self.agent_config,
            "task": self.task,
            "files": [str(f) for f in self.files],
            "notes": self.notes,
        }


def environment_report() -> dict[str, Any]:
    """What is actually available here, checked rather than assumed."""
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "tooltrace": FRAMEWORK_VERSION,
        "git": bool(shutil.which("git")),
        # Docker is optional: the local sandbox works without it, and
        # `docs/threat-model.md` is explicit that container isolation is the
        # answer to what the local sandbox does not stop.
        "docker": bool(shutil.which("docker")),
    }


def available_tasks() -> list[str]:
    from tooltrace.tasks.loader import load_all_tasks

    return sorted(task.id for task in load_all_tasks())


def _starter_task(tasks: list[str]) -> str:
    """A short, deterministic, offline task to prove the wiring end to end.

    Preferring a file-editing task is not arbitrary: it needs no network, no
    fixtures and no credentials, so a failure is about the agent rather than
    about the environment.
    """
    for candidate in ("file-editing/fix-config-typo", "json-csv-transform/users-to-csv"):
        if candidate in tasks:
            return candidate
    return tasks[0] if tasks else ""


def build_config(
    adapter: str, *, command: str, base_url: str, model: str, api_key_env: str
) -> dict[str, Any]:
    """The `--agent-config` payload for the chosen adapter."""
    if adapter == "subprocess":
        return {
            "command": command or DEFAULT_COMMAND,
            "timeout_seconds": 120,
        }
    if adapter == "openai_compat":
        return {
            "base_url": base_url or "http://localhost:11434/v1",
            "model": model or "qwen2.5-coder",
            # The *name* of the variable, never its value. A generated file is
            # committed; a key written into one is a key published.
            "api_key_env": api_key_env or "OPENAI_API_KEY",
        }
    return {"script": []}


def plan(
    directory: Path,
    *,
    adapter: str,
    command: str = "",
    base_url: str = "",
    model: str = "",
    api_key_env: str = "",
    task: str = "",
    write_workflow: bool = True,
) -> InitPlan:
    """Decide everything before touching the filesystem."""
    if adapter not in ADAPTERS:
        raise ValueError(f"unknown adapter {adapter!r}; choose one of {sorted(ADAPTERS)}")

    tasks = available_tasks()
    chosen = task or _starter_task(tasks)
    result = InitPlan(
        directory=directory,
        adapter=adapter,
        agent_config=build_config(
            adapter, command=command, base_url=base_url, model=model, api_key_env=api_key_env
        ),
        task=chosen,
        write_workflow=write_workflow,
    )

    if task and tasks and task not in tasks:
        # Not fatal: a task can come from a pack installed later. But silently
        # writing a config that names a task nobody has is how a user ends up
        # debugging the harness instead of their agent.
        result.notes.append(
            f"task {task!r} is not currently installed; `tooltrace tasks` lists {len(tasks)} available"
        )
    if adapter == "subprocess" and "{objective}" not in result.agent_config["command"]:
        result.notes.append(
            "the command has no {objective} placeholder, so your agent will not "
            "receive the task description"
        )
    if adapter == "openai_compat":
        result.notes.append(
            f"set {result.agent_config['api_key_env']} in your environment; "
            "the key is never written to the config"
        )
    if not tasks:
        result.notes.append("no task packs are installed, so there is nothing to run")
    return result


def workflow_yaml(adapter: str, task: str) -> str:
    """A CI workflow using this repository's own composite action."""
    task_line = f"          tasks: {task}\n" if task else ""
    return f"""# Generated by `tooltrace init`. Runs an agent-reliability benchmark on
# every pull request and fails when the measured success rate drops.
#
# `min-success-rate` starts at 0 deliberately: a threshold you have not measured
# is a guess, and a guessed threshold either blocks every PR or blocks none.
# Run this a few times, read the reported confidence interval, then set a floor
# the interval actually supports.
name: Agent reliability

on:
  pull_request:
  workflow_dispatch:

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: webdevsamran/tooltrace-bench@main
        with:
          agent: {adapter}
          agent-config: ${{{{ vars.TOOLTRACE_AGENT_CONFIG }}}}
{task_line}          runs: 3
          min-success-rate: "0"
"""


def write(plan_: InitPlan, *, force: bool = False) -> list[str]:
    """Write the plan. Returns problems; writes nothing when any are found."""
    directory = plan_.directory
    targets: list[tuple[Path, str]] = [
        (directory / CONFIG_NAME, json.dumps(plan_.agent_config, indent=2) + "\n")
    ]
    if plan_.write_workflow:
        targets.append((directory / WORKFLOW_PATH, workflow_yaml(plan_.adapter, plan_.task)))

    # Every collision is reported at once. Discovering them one `--force` at a
    # time is the kind of small cruelty a scaffolding tool gets remembered for.
    existing = [str(path) for path, _ in targets if path.exists()]
    if existing and not force:
        return [f"{path} already exists; pass --force to overwrite" for path in existing]

    for path, content in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        plan_.files.append(path)
    return []


def config_is_useful(plan_: InitPlan) -> bool:
    """Does the written config carry anything a run needs?

    `scripted` is the exception: it has no configuration of its own, and each
    task ships the script that solves it. Passing an empty `{"script": []}`
    would *override* that and fail -- so a printed command that includes it
    would be a command that does not work, which is precisely the kind of
    generated-and-never-run artifact this project keeps finding.
    """
    if plan_.adapter == "scripted":
        return bool(plan_.agent_config.get("script"))
    return bool(plan_.agent_config)


def first_run_command(plan_: InitPlan) -> list[str]:
    """The exact command the user could type themselves. No hidden flags."""
    command = ["tooltrace", "run", "--task", plan_.task, "--agent", plan_.adapter]
    if config_is_useful(plan_):
        command += ["--agent-config", f"@{CONFIG_NAME}"]
    return command


def _config_flag(plan_: InitPlan) -> str:
    return f" --agent-config @{CONFIG_NAME}" if config_is_useful(plan_) else ""


def verify(plan_: InitPlan) -> dict[str, Any]:
    """Run one task with the configured agent and report what happened.

    In-process rather than through a subprocess, so this works from a source
    checkout and from an installed wheel identically, and so a failure surfaces
    as a message rather than as an exit code with no context.
    """
    from tooltrace.runners.runner import TaskRunner
    from tooltrace.tasks.loader import load_all_tasks

    task = next((t for t in load_all_tasks() if t.id == plan_.task), None)
    if task is None:
        return {"ran": False, "reason": f"task {plan_.task!r} is not installed"}
    config = plan_.agent_config
    if plan_.adapter == "scripted" and not config.get("script"):
        # The demo adapter has no script of its own; each task ships the one
        # that solves it. Without this the deterministic demo fails, which would
        # make `init --agent scripted` look broken when it is the one path
        # guaranteed to work.
        script = task.metadata.get("scripted_script")
        if isinstance(script, list):
            config = {"script": script}
    try:
        result, _events, _diff = TaskRunner().run(task, plan_.adapter, config)
    except Exception as exc:
        # A first run that cannot start is the most useful thing this command
        # can report, and the least useful thing it can hide.
        return {"ran": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "ran": True,
        "success": bool(result.success),
        "score": result.score.total,
        "failure_reason": result.failure_reason.value,
        "steps": result.steps,
        "wall_ms": result.wall_ms,
    }


def _which_agent_interactively(stream: Any) -> str:
    """Ask, when there is someone to ask. Never blocks a non-interactive run."""
    options = list(ADAPTERS)
    print("Which describes how your agent is invoked?", file=sys.stderr)
    for index, name in enumerate(options, start=1):
        print(f"  {index}. {name} - {ADAPTERS[name]}", file=sys.stderr)
    print(f"Choose 1-{len(options)} [1]: ", end="", file=sys.stderr, flush=True)
    answer = (stream.readline() or "").strip()
    if not answer:
        return options[0]
    if answer.isdigit() and 1 <= int(answer) <= len(options):
        return options[int(answer) - 1]
    if answer in ADAPTERS:
        return answer
    print(f"Not a choice: {answer!r}. Using {options[0]}.", file=sys.stderr)
    return options[0]


def choose_adapter(
    explicit: str | None, *, stdin: Any = None, interactive: bool | None = None
) -> str:
    """The adapter, from the flag, from a prompt, or from the safe default."""
    if explicit:
        return explicit
    stream = stdin if stdin is not None else sys.stdin
    is_tty = (
        interactive if interactive is not None else bool(getattr(stream, "isatty", lambda: False)())
    )
    if is_tty:
        return _which_agent_interactively(stream)
    # Non-interactive: `subprocess` wraps any CLI, which is the case that
    # applies to the most agents. The choice is printed, never silent.
    return "subprocess"


def render(plan_: InitPlan, environment: dict[str, Any], run: dict[str, Any] | None) -> str:
    """The human report. Written to be read once and acted on immediately."""
    lines = [
        # ASCII only. A Windows console in its default code page renders "·"
        # and em dashes as question marks, and a setup report that looks
        # corrupted is the worst possible first impression of a tool.
        f"tooltrace {environment['tooltrace']} | python {environment['python']}"
        f" | git {'yes' if environment['git'] else 'no'}"
        f" | docker {'yes' if environment['docker'] else 'no'}",
        "",
        f"Adapter:  {plan_.adapter} - {ADAPTERS[plan_.adapter]}",
        f"Task:     {plan_.task or '(none installed)'}",
        "Wrote:    " + (", ".join(str(f) for f in plan_.files) or "(nothing)"),
    ]
    if plan_.notes:
        lines += ["", "Notes:"] + [f"  - {note}" for note in plan_.notes]

    if run is not None:
        lines += ["", "First run:"]
        if not run.get("ran"):
            lines += [
                f"  did not run: {run.get('reason')}",
                "  Fix the config above and run the command below; nothing else is needed.",
            ]
        elif run.get("success"):
            lines += [
                f"  passed | score {run['score']:.2f} | {run['steps']} steps | "
                f"{run['wall_ms']:.0f} ms",
                "  One passing run is wiring, not reliability. Repeat it to get an interval:",
                f"    tooltrace benchmark --agent {plan_.adapter}"
                f"{_config_flag(plan_)} --runs 20 --summary",
            ]
        else:
            lines += [
                f"  failed | {run['failure_reason']} | score {run['score']:.2f}",
                "  That is a real measurement, not a setup problem. Inspect it:",
                f"    tooltrace run --task {plan_.task} --agent {plan_.adapter}"
                f"{_config_flag(plan_)} --out runs",
            ]
    else:
        lines += ["", "Next:", "  " + " ".join(first_run_command(plan_))]
    return "\n".join(lines)


def run_init(
    directory: Path,
    *,
    adapter: str | None = None,
    command: str = "",
    base_url: str = "",
    model: str = "",
    api_key_env: str = "",
    task: str = "",
    write_workflow: bool = True,
    force: bool = False,
    do_verify: bool = True,
    stdin: Any = None,
    interactive: bool | None = None,
) -> tuple[int, dict[str, Any]]:
    """Everything `init` does, returning an exit code and a JSON payload."""
    environment = environment_report()
    chosen = choose_adapter(adapter, stdin=stdin, interactive=interactive)
    plan_ = plan(
        directory,
        adapter=chosen,
        command=command,
        base_url=base_url,
        model=model,
        api_key_env=api_key_env,
        task=task,
        write_workflow=write_workflow,
    )
    problems = write(plan_, force=force)
    if problems:
        return 2, {"ok": False, "problems": problems, "plan": plan_.to_dict()}

    run = verify(plan_) if do_verify and plan_.task else None
    payload = {
        # `ok` is about the scaffold, not about the agent. A failing first run
        # is a successful init that measured something, and conflating the two
        # would make a real result look like a broken tool.
        "ok": True,
        "environment": environment,
        "plan": plan_.to_dict(),
        "first_run": run,
        "next_command": first_run_command(plan_),
        "report": render(plan_, environment, run),
    }
    return 0, payload


def _agent_config_from(value: str) -> dict[str, Any]:
    """Shared by the CLI: `@path` reads a file, anything else is inline JSON."""
    if value.startswith("@"):
        return dict(json.loads(Path(value[1:]).read_text(encoding="utf-8")))
    return dict(json.loads(value))


def probe_command(command: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Does the configured command exist? Cheap check, run before a real run."""
    executable = command.split()[0] if command.strip() else ""
    if not executable:
        return {"found": False, "reason": "empty command"}
    if shutil.which(executable):
        return {"found": True, "executable": executable}
    try:
        subprocess.run([executable, "--version"], capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return {"found": False, "reason": f"{executable!r} is not on PATH"}
    return {"found": True, "executable": executable}
