"""Writing a task's attachments into a workspace, in exactly one place.

Three functions materialise a workspace -- the local sandbox, the Docker
sandbox, and replay -- and each of them grew its own copy of the
`starting_workspace` loop. That is survivable for text because the three copies
are three lines each. It is not survivable for attachments: a replay that
skipped the image would re-run the task against a workspace the original never
had, report a mismatch, and the mismatch would be the replayer's.

So there is one function, and all three call it.
"""

from __future__ import annotations

from pathlib import Path

from tooltrace.core.exceptions import SandboxError
from tooltrace.core.models import TaskDefinition


def materialize(task: TaskDefinition, workspace: Path) -> dict[str, str]:
    """Write every attachment into *workspace*. Returns {path: sha256}.

    The digest is returned rather than logged so the caller can record what it
    actually wrote. `Attachment.decoded` has already refused any content whose
    bytes disagree with a declared `sha256`, so a returned digest is the digest
    of the bytes on disk.
    """
    written: dict[str, str] = {}
    for attachment in task.attachments:
        relative = Path(attachment.path)
        if relative.is_absolute() or ".." in relative.parts:
            # The workspace boundary is enforced for every tool call; an
            # attachment path is the one filesystem write that happens before
            # any tool runs, so it is checked here instead.
            raise SandboxError(f"attachment path escapes the workspace: {attachment.path}")
        target = workspace / relative
        try:
            raw = attachment.decoded()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        except OSError as exc:
            raise SandboxError(f"failed to write attachment {attachment.path}: {exc}") from exc
        except ValueError as exc:
            raise SandboxError(str(exc)) from exc
        written[attachment.path] = attachment.digest()
    return written
