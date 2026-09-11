"""Whether an adapter can put an image in front of the model, and how.

`Attachment` has been declarable since the v2 protocol was written and no code
in this repository ever read it, so a multimodal task could be *written* and
never *run*. This is the half that was missing, and it is mostly a table --
because the interesting question is not how to base64 a PNG, it is what happens
to a task carrying one when the adapter cannot send it.

The answer has to be **skip, never score**. A text-only model asked "what error
code is in the screenshot" will answer, fluently and wrongly, and a harness that
recorded that as the agent's failure would be reporting a property of itself.
This is the same rule `requires_tools` already applies to a missing `cargo`, for
the same reason, and it reuses the same machinery
(:mod:`tooltrace.tasks.availability`).

**Adapter support is necessary and not sufficient.** `openai_compat` can send an
image block to anything speaking the OpenAI chat API -- including a local
llama.cpp server running a text-only 7B that will either error or silently drop
it. Whether the *model* can see is a property of the model, and nothing here
claims to know it. What the table records is whether the adapter has somewhere
to put the bytes at all, which is checkable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tooltrace.core.models import Attachment

#: The adapter sends the bytes in the request body, as a content block.
INLINE = "inline"
#: The adapter cannot send bytes, but runs against the workspace the attachment
#: was written into, so the agent can open the file with its own tooling.
WORKSPACE = "workspace"
#: Neither. A task with attachments is skipped against this adapter.
NONE = "none"


@dataclass(frozen=True)
class VisionSupport:
    adapter: str
    state: str
    #: Where the bytes go, or why they go nowhere.
    field: str
    note: str

    @property
    def can_reach_the_image(self) -> bool:
        return self.state in (INLINE, WORKSPACE)


VISION_SUPPORT: dict[str, VisionSupport] = {
    "openai_compat": VisionSupport(
        adapter="openai_compat",
        state=INLINE,
        field="messages[].content[].image_url.url (data: URI)",
        note=(
            "The chat-completions image block. Every local server this project "
            "presets -- Ollama, llama.cpp, LM Studio, vLLM, SGLang -- accepts the "
            "same shape, and whether the loaded weights can see is the model's "
            "property, not the adapter's"
        ),
    ),
    "anthropic": VisionSupport(
        adapter="anthropic",
        state=INLINE,
        field="messages[].content[].source (base64)",
        note="The Messages API carries the media type alongside the data rather than in a URI",
    ),
    "gemini": VisionSupport(
        adapter="gemini",
        state=INLINE,
        field="contents[].parts[].inline_data",
        note="`inline_data` for bytes sent with the request; the Files API is not used here",
    ),
    "subprocess": VisionSupport(
        adapter="subprocess",
        state=WORKSPACE,
        field="(the file, on disk)",
        note=(
            "The child runs with `cwd` set to the workspace, so the attachment is a "
            "file it can open. Whether it does is outside this harness -- which is "
            "the same thing this adapter's docstring already says about everything else"
        ),
    ),
    "streaming": VisionSupport(
        adapter="streaming",
        state=WORKSPACE,
        field="(the file, on disk)",
        note="Same as subprocess: the workspace is shared, the protocol is not",
    ),
    "scripted": VisionSupport(
        adapter="scripted",
        state=NONE,
        field="(no model)",
        note=(
            "A fixed script with no model behind it. It could be made to pass a vision "
            "task by hardcoding the answer, which would measure nothing"
        ),
    ),
}


def support_for(adapter: str) -> VisionSupport:
    return VISION_SUPPORT.get(
        adapter,
        VisionSupport(
            adapter=adapter,
            state=NONE,
            field="(unknown)",
            note=(
                "not a built-in adapter. A plugin that can send images should register "
                "itself in VISION_SUPPORT; until it does, attachment tasks are skipped "
                "rather than run blind"
            ),
        ),
    )


class UnsupportedAttachment(ValueError):
    """An image was handed to an adapter with nowhere to put it."""


def image_block(attachment: Attachment, dialect: str) -> dict[str, Any]:
    """One provider-shaped content block carrying the attachment's bytes.

    Raises rather than degrading to a text placeholder. A block silently
    replaced by "[image omitted]" is the failure this module exists to prevent:
    the request succeeds, the model answers, and the score is a measurement of
    the omission.
    """
    import base64

    # Re-encoded from the decoded bytes rather than passed through: the value on
    # the task is wrapped for a human to read, and a data: URI with newlines in
    # it is not a URI.
    data = base64.b64encode(attachment.decoded()).decode("ascii")
    if dialect == "openai":
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{attachment.media_type};base64,{data}"},
        }
    if dialect == "anthropic":
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": attachment.media_type,
                "data": data,
            },
        }
    if dialect == "gemini":
        return {"inline_data": {"mime_type": attachment.media_type, "data": data}}
    raise UnsupportedAttachment(f"no image block shape for dialect {dialect!r}")


def content_with_images(
    text: str, attachments: list[Attachment], dialect: str
) -> str | list[dict[str, Any]]:
    """A user message body: the plain string when there is nothing to attach.

    Returning the bare string in the common case is deliberate. Wrapping every
    text-only turn in a one-element content array would change the request body
    of every existing run, and a benchmark whose numbers move because its
    serializer changed is not measuring the agent.
    """
    if not attachments:
        return text
    blocks: list[dict[str, Any]] = [image_block(a, dialect) for a in attachments]
    if dialect == "gemini":
        return [*blocks, {"text": text}]
    return [*blocks, {"type": "text", "text": text}]


def report() -> dict[str, Any]:
    """What a task carrying an image can actually reach, per adapter."""
    rows = [
        {
            "adapter": spec.adapter,
            "state": spec.state,
            "field": spec.field,
            "note": spec.note,
        }
        for spec in sorted(VISION_SUPPORT.values(), key=lambda s: s.adapter)
    ]
    inline = [r["adapter"] for r in rows if r["state"] == INLINE]
    skipped = [r["adapter"] for r in rows if r["state"] == NONE]
    return {
        "adapters": rows,
        "inline": inline,
        "skipped": skipped,
        "statement": (
            f"{len(inline)} of {len(rows)} adapters send an image in the request "
            f"({', '.join(inline)}); tasks with attachments are skipped against "
            f"{', '.join(skipped) or 'none'}. Sending an image is not the same as the "
            "model being able to see it, and that part is not measured here"
        ),
    }
