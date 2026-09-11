"""A multimodal task, end to end, with no model and no network.

`Attachment` was declarable from the day the v2 protocol was written -- "never
embedded", said the docstring -- and nothing in this repository ever read the
field. A multimodal task could be authored and could not be run. The gap is the
same one this project keeps finding in itself, and closing it needs two things
the plan's grade of **S** ("schema only") would not have given:

1. The image has to actually reach the adapter. Proven here by an agent that
   *reads the pixels*: `BitmapReaderAgent` decodes the PNG out of the request
   body it was handed and answers from what it finds. It is not a model and is
   not pretending to be one -- it is the smallest thing that can distinguish
   "the harness delivered a readable image" from "the harness delivered a
   string that mentions an image".

2. A task carrying an image must be *skipped* against an adapter that cannot
   send one, never scored. A text-only model asked what error code is in a
   screenshot will answer fluently and wrongly, and the pack is built so that
   the plausible wrong answer is sitting in the ticket text waiting to be
   copied.

**What is not established here.** That any particular vision model can read a
5x7 bitmap font at scale 6. That needs an API key and a network, and no test in
this file claims it. `docs/feature-status.md` grades the row **E** for exactly
that reason.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from tooltrace.agents.chat_base import ChatProtocolAgent
from tooltrace.agents.vision import (
    INLINE,
    NONE,
    VISION_SUPPORT,
    UnsupportedAttachment,
    content_with_images,
    image_block,
    report,
    support_for,
)
from tooltrace.core.models import Attachment
from tooltrace.core.registry import agent_registry
from tooltrace.runners.runner import TaskRunner
from tooltrace.tasks.availability import availability, partition
from tooltrace.tasks.imaging import (
    UnrenderableCharacter,
    decode_gray,
    read_text,
    render_grid,
    render_text_png,
)
from tooltrace.tasks.loader import load_all_tasks

TASK_ID = "multimodal/read-error-code-from-screenshot"
#: The answer, which appears in the image and nowhere in the text.
CODE = "ERR-7F2C-4419"
#: The plausible wrong answer, which appears in the text and not in the image.
DECOY = "ERR-3A19-8802"


def the_task():
    task = next((t for t in load_all_tasks() if t.id == TASK_ID), None)
    assert task is not None, f"{TASK_ID} is not installed"
    return task


# --- the renderer is its own inverse ----------------------------------------


@pytest.mark.parametrize("scale", [1, 2, 6, 9])
def test_text_survives_a_render_and_a_read(scale: int) -> None:
    lines = ["SYSTEM ERROR", "CODE: 0X8007000E", "RETRY   CLOSE"]
    assert read_text(render_text_png(lines, scale=scale)) == lines


def test_the_pixel_scale_is_inferred_rather_than_assumed() -> None:
    """`read_text` is given no parameters and still has to agree with the render."""
    assert read_text(render_text_png(["ABC 019"], scale=7)) == ["ABC 019"]


def test_a_character_with_no_glyph_is_refused() -> None:
    """Substituting a blank would put an image in front of a model that does
    not say what the task claims it says."""
    with pytest.raises(UnrenderableCharacter, match="no glyph"):
        render_text_png(["code: érr"])


def test_the_decoder_refuses_a_png_it_did_not_write() -> None:
    with pytest.raises(ValueError, match="not a PNG"):
        decode_gray(b"GIF89a not really")


def test_lowercase_is_rendered_as_uppercase_not_dropped() -> None:
    assert read_text(render_text_png(["err-7f2c"])) == ["ERR-7F2C"]


# --- the committed image says what the task claims ---------------------------


def test_the_screenshot_is_the_image_the_task_metadata_describes() -> None:
    """The answer and the pixels cannot drift apart.

    A committed binary nobody can diff is the usual way a fixture stops matching
    the task that depends on it. Here the task records the lines it was rendered
    from, and this re-renders them and compares grids -- not bytes, because zlib
    output is not contractually stable across versions and the pixels are what
    the claim is about.
    """
    task = the_task()
    spec = task.metadata["attachment_render"]
    rendered = render_grid(spec["lines"], scale=int(spec["scale"]))
    assert decode_gray(task.attachments[0].decoded()) == rendered


def test_the_answer_is_in_the_image() -> None:
    task = the_task()
    assert CODE in read_text(task.attachments[0].decoded())


def test_the_answer_is_nowhere_in_the_text() -> None:
    """If it leaked into the prompt, a text-only model would pass without seeing."""
    task = the_task()
    text = " ".join([task.objective, task.description, *task.starting_workspace.values()])
    assert CODE not in text
    assert DECOY in text, "the plausible wrong answer has to be available to copy"


def test_the_declared_digest_is_checked_rather_than_trusted() -> None:
    attachment = the_task().attachments[0]
    assert attachment.sha256 and attachment.digest() == attachment.sha256

    tampered = attachment.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ValueError, match="hashes to"):
        tampered.decoded()


def test_an_undeclared_digest_is_not_a_passing_one() -> None:
    """An empty `sha256` means "not declared", not "checked and fine"."""
    attachment = Attachment(
        path="x.png", media_type="image/png", content_base64=base64.b64encode(b"x").decode()
    )
    assert attachment.sha256 == ""
    assert attachment.decoded() == b"x"


def test_wrapped_base64_decodes() -> None:
    """YAML folds a `>-` block onto one line with spaces in it."""
    raw = base64.b64encode(b"some bytes here").decode()
    wrapped = " ".join(raw[i : i + 4] for i in range(0, len(raw), 4))
    assert Attachment(path="a", media_type="image/png", content_base64=wrapped).decoded() == (
        b"some bytes here"
    )


# --- the attachment reaches the workspace -----------------------------------


def test_the_attachment_is_written_into_the_sandbox() -> None:
    from tooltrace.sandbox.local import TempWorkspaceSandbox

    task = the_task()
    with TempWorkspaceSandbox() as sandbox:
        workspace = sandbox.start(task)
        written = workspace / "screenshot.png"
        assert written.is_file()
        assert written.read_bytes() == task.attachments[0].decoded()


def test_an_attachment_path_cannot_escape_the_workspace(tmp_path) -> None:
    from tooltrace.core.exceptions import SandboxError
    from tooltrace.tasks.attachments import materialize

    task = the_task().model_copy(
        update={
            "attachments": [
                Attachment(
                    path="../escaped.png",
                    media_type="image/png",
                    content_base64=base64.b64encode(b"x").decode(),
                )
            ]
        }
    )
    with pytest.raises(SandboxError, match="escapes the workspace"):
        materialize(task, tmp_path)


def test_a_modified_binary_is_visible_in_a_workspace_snapshot(tmp_path) -> None:
    """Every binary used to snapshot as the same fixed string.

    Before and after were then identical for a file the agent had rewritten, and
    the diff was empty in exactly the case that matters.
    """
    from tooltrace.sandbox.diff import snapshot

    (tmp_path / "a.png").write_bytes(b"\x89PNG original")
    before = snapshot(tmp_path)
    (tmp_path / "a.png").write_bytes(b"\x89PNG replaced")
    after = snapshot(tmp_path)
    assert before["a.png"] != after["a.png"]


# --- the skip rule ----------------------------------------------------------


def test_a_vision_task_is_skipped_against_an_adapter_that_cannot_see() -> None:
    state = availability(the_task(), "scripted")
    assert not state.runnable
    assert "nowhere to put an image" in state.reason


def test_the_same_task_is_runnable_against_an_adapter_that_can() -> None:
    assert availability(the_task(), "anthropic").runnable


def test_an_unnamed_agent_does_not_make_every_vision_task_unrunnable() -> None:
    """`tooltrace tasks` lists what exists without knowing what will run it."""
    assert availability(the_task()).runnable
    assert availability(the_task(), None).runnable


def test_partition_reports_the_skip_with_its_reason() -> None:
    runnable, skipped = partition([the_task()], "scripted")
    assert runnable == []
    assert len(skipped) == 1 and "attachment" in skipped[0][1]


def test_the_task_listing_can_be_asked_about_a_specific_adapter(capsys) -> None:
    """Without `--agent`, a listing cannot know an attachment task is unrunnable."""
    from tooltrace.cli.main import main

    main(["tasks", "--agent", "scripted", "--json"])
    rows = json.loads(capsys.readouterr().out)
    blocked = [row["id"] for row in rows if not row["runnable_here"]]
    assert TASK_ID in blocked

    main(["tasks", "--agent", "anthropic", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert TASK_ID not in [row["id"] for row in rows if not row["runnable_here"]]


def test_the_listing_reports_how_many_attachments_a_task_carries(capsys) -> None:
    from tooltrace.cli.main import main

    main(["tasks", "--json"])
    rows = json.loads(capsys.readouterr().out)
    row = next(r for r in rows if r["id"] == TASK_ID)
    assert row["attachments"] == 1


def test_the_cli_skips_rather_than_scoring_it(capsys) -> None:
    from tooltrace.cli.main import main

    code = main(["run", "--task", TASK_ID, "--agent", "scripted", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0, "a skip is not a failed build"
    assert payload["skipped"] is True
    assert "attachment" in payload["reason"]


# --- an agent that actually reads the image ---------------------------------


class BitmapReaderAgent(ChatProtocolAgent):
    """Answers from the pixels it was sent. Not a model, and not a mock either.

    A mock would return a canned reply and prove only that the loop runs. This
    pulls the data URI out of the request body it was handed, decodes the PNG,
    and reads the code off it -- so it fails if the harness sends no image,
    sends the wrong one, or sends a text placeholder.
    """

    name = "bitmap_reader"
    dialect = "openai"

    def complete(
        self, system: str, history: list[dict[str, str]], user: str | list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any] | None]:
        if isinstance(user, list):
            urls = [block["image_url"]["url"] for block in user if block.get("type") == "image_url"]
            assert urls, "an attachment turn carried no image block"
            raw = base64.b64decode(urls[0].split(",", 1)[1])
            lines = read_text(raw)
            found = next((line for line in lines if line.startswith("ERR-")), "")
            self.seen = found
            return (
                json.dumps(
                    {
                        "action": "tool",
                        "tool": "write_file",
                        "args": {"path": "code.txt", "content": found},
                    }
                ),
                None,
            )
        return json.dumps({"action": "finish", "message": "wrote the code"}), None


class BlindGuesserAgent(ChatProtocolAgent):
    """Ignores the image and copies the code out of the ticket text.

    The specific plausible mistake this task exists to catch, per the rule in
    `tests/test_new_packs_discriminate.py`: a pack nobody has seen fail is a
    pack that might be measuring nothing.
    """

    name = "blind_guesser"
    dialect = "openai"

    def complete(
        self, system: str, history: list[dict[str, str]], user: str | list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any] | None]:
        if isinstance(user, list):
            return (
                json.dumps(
                    {
                        "action": "tool",
                        "tool": "write_file",
                        "args": {"path": "code.txt", "content": DECOY},
                    }
                ),
                None,
            )
        return json.dumps({"action": "finish", "message": "done"}), None


@pytest.fixture(autouse=True)
def _register_test_adapters():
    """Registered for the test, and removed again.

    The registry is process-global. Leaving these in it made
    `test_every_built_in_adapter_is_in_the_table` fail in `test_seed_control.py`
    -- correctly: an adapter in the registry with no row in the seed table is
    exactly what that test exists to catch, and a test fixture is no more
    entitled to a silent exemption than a real adapter is.
    """
    before = dict(agent_registry._items)
    agent_registry.register("bitmap_reader")(BitmapReaderAgent)
    agent_registry.register("blind_guesser")(BlindGuesserAgent)
    yield
    agent_registry._items.clear()
    agent_registry._items.update(before)


def test_an_agent_that_reads_the_image_passes() -> None:
    result, _events, _diff = TaskRunner().run(the_task(), "bitmap_reader", {})
    assert result.success, f"score={result.score.total} components={result.score.components}"


def test_an_agent_that_copies_the_decoy_fails() -> None:
    result, _events, _diff = TaskRunner().run(the_task(), "blind_guesser", {})
    assert not result.success, (
        "an agent that never looked at the screenshot PASSES; the task measures nothing"
    )


# --- what the adapters do with an image -------------------------------------


def test_a_text_only_turn_is_still_a_plain_string() -> None:
    """Wrapping every existing turn in a content array would change every
    request body, and a benchmark whose numbers move because its serializer
    changed is not measuring the agent."""
    assert content_with_images("hello", [], "openai") == "hello"


@pytest.mark.parametrize("dialect", ["openai", "anthropic", "gemini"])
def test_every_dialect_carries_the_bytes(dialect: str) -> None:
    attachment = the_task().attachments[0]
    block = image_block(attachment, dialect)
    flat = json.dumps(block)
    assert base64.b64encode(attachment.decoded()).decode()[:64] in flat


def test_the_data_uri_has_no_newlines_in_it() -> None:
    """The value on the task is wrapped for a human to read.

    A data: URI with a line break in it is not a URI, and the failure would be a
    provider-side 400 nobody could read.
    """
    url = image_block(the_task().attachments[0], "openai")["image_url"]["url"]
    assert "\n" not in url and " " not in url


def test_gemini_puts_the_text_part_last() -> None:
    parts = content_with_images("what code", the_task().attachments, "gemini")
    assert isinstance(parts, list)
    assert "inline_data" in parts[0] and parts[-1] == {"text": "what code"}


def test_an_unknown_dialect_raises_rather_than_dropping_the_image() -> None:
    with pytest.raises(UnsupportedAttachment, match="no image block shape"):
        image_block(the_task().attachments[0], "cohere")


def test_an_adapter_with_no_dialect_refuses_the_task() -> None:
    """The whole point: silence here would be scored as the agent's failure."""

    class NoDialect(ChatProtocolAgent):
        name = "no_dialect"

        def complete(self, system, history, user):  # pragma: no cover - never reached
            raise AssertionError("the image should never have got this far")

    agent_registry.register("no_dialect")(NoDialect)
    result, _events, _diff = TaskRunner().run(the_task(), "no_dialect", {})
    assert not result.success


# --- the image is sent once ------------------------------------------------


class CountingAgent(ChatProtocolAgent):
    """Counts the turns that carried an image."""

    name = "counting"
    dialect = "openai"
    turns_with_images = 0
    total_turns = 0

    def complete(
        self, system: str, history: list[dict[str, str]], user: str | list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any] | None]:
        type(self).total_turns += 1
        if isinstance(user, list):
            type(self).turns_with_images += 1
        if type(self).total_turns < 3:
            return (
                json.dumps({"action": "tool", "tool": "read_file", "args": {"path": "ticket.md"}}),
                None,
            )
        return json.dumps({"action": "finish", "message": "done"}), None


def test_the_image_goes_once_not_every_turn() -> None:
    """An image resent every step grows the bill linearly and invisibly.

    The same reason `HISTORY_TURNS` is bounded: a benchmark that quietly triples
    its own token cost on long tasks is measuring its own accumulation.
    """
    CountingAgent.turns_with_images = 0
    CountingAgent.total_turns = 0
    agent_registry.register("counting")(CountingAgent)
    TaskRunner().run(the_task(), "counting", {})
    assert CountingAgent.total_turns >= 2, "the test needs more than one turn to be meaningful"
    assert CountingAgent.turns_with_images == 1


def test_every_turn_is_available_for_anyone_who_would_rather_pay() -> None:
    CountingAgent.turns_with_images = 0
    CountingAgent.total_turns = 0
    agent_registry.register("counting")(CountingAgent)
    TaskRunner().run(the_task(), "counting", {"attachment_policy": "every_turn"})
    assert CountingAgent.turns_with_images == CountingAgent.total_turns


def test_the_model_is_told_the_image_will_not_come_back() -> None:
    """A model that assumed the image was still there would answer from a
    memory it does not have."""
    agent = BitmapReaderAgent({})
    from tooltrace.core.models import AgentContext

    agent.initialize(
        AgentContext(
            task_id=TASK_ID,
            objective="x",
            description="",
            allowed_tools=["write_file"],
            attachments=the_task().attachments,
        )
    )
    assert "first message only" in agent.system_prompt()


# --- the support table ------------------------------------------------------


def test_every_registered_adapter_has_a_vision_row() -> None:
    """A missing row defaults to "cannot", which is the safe direction -- but a
    silent default is how an adapter that *can* see ends up skipping tasks it
    could have run."""
    import tooltrace.agents  # noqa: F401  (importing registers the built-ins)

    # The adapters this file registers are excluded by name rather than by a
    # pattern: a pattern would also excuse a real adapter somebody named badly.
    test_only = {"bitmap_reader", "blind_guesser", "counting", "no_dialect"}
    missing = sorted(set(agent_registry.names()) - set(VISION_SUPPORT) - test_only)
    assert missing == [], f"adapters with no declared vision support: {missing}"


def test_an_unknown_adapter_is_assumed_blind() -> None:
    spec = support_for("some-plugin-nobody-here-wrote")
    assert spec.state == NONE
    assert not spec.can_reach_the_image


def test_the_report_does_not_claim_the_model_can_see() -> None:
    """Sending an image and the model reading it are different facts."""
    statement = report()["statement"]
    assert "not measured here" in statement
    assert report()["inline"] == sorted(
        a for a, s in VISION_SUPPORT.items() if s.state == INLINE
    ), "the report must be generated from the table, not written next to it"


def test_the_scripted_adapter_is_deliberately_blind() -> None:
    """It could be made to pass by hardcoding the answer, which measures nothing."""
    assert support_for("scripted").state == NONE
