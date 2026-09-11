#!/usr/bin/env python
"""Render text into a task attachment, ready to paste into a pack.

A multimodal task needs an image, and the two obvious ways to get one both
break the property that makes a `.tooltrace` bundle worth having. A photograph
or a screenshot is a binary nobody can diff, so nothing checks that it still
says what the task claims. A path to a file on disk stops resolving the moment
the bundle moves. So the bytes travel inside the task, and they are *generated*,
which means a test can re-render them and assert the pixels and the expected
answer have not drifted apart.

    python scripts/render_attachment.py --path screenshot.png \\
        "INSTALLER FAILED" "" "ERROR CODE" "ERR-7F2C-4419"

Prints a YAML `attachments:` block. The font is uppercase-only and small on
purpose -- see `tooltrace/tasks/imaging.py` -- and a character it has no glyph
for is refused rather than silently blanked.

This does **not** tell you whether a vision model can read the result. Nothing
in this repository does; that needs a key and a network.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tooltrace.tasks.imaging import (
    UnrenderableCharacter,
    dimensions,
    read_text,
    render_text_png,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lines", nargs="+", help="one argument per line of text")
    parser.add_argument("--path", default="screenshot.png", help="workspace path for the image")
    parser.add_argument("--scale", type=int, default=6, help="image pixels per font pixel")
    parser.add_argument("--out", help="also write the PNG here, to look at it")
    args = parser.parse_args(argv)

    try:
        png = render_text_png(args.lines, scale=args.scale)
    except UnrenderableCharacter as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Read it back before printing it. A block that does not say what was asked
    # for is the one thing this script must not emit.
    recovered = read_text(png)
    expected = [line.upper() for line in args.lines]
    if recovered != expected:
        print(f"error: the image reads back as {recovered}, not {expected}", file=sys.stderr)
        return 1

    if args.out:
        Path(args.out).write_bytes(png)

    encoded = base64.b64encode(png).decode("ascii")
    width, height = dimensions(png)
    print(f"# {width}x{height}, {len(png)} bytes", file=sys.stderr)
    print("attachments:")
    print(f"  - path: {args.path}")
    print("    media_type: image/png")
    print(f"    sha256: {hashlib.sha256(png).hexdigest()}")
    print("    content_base64: >-")
    for index in range(0, len(encoded), 76):
        print(f"      {encoded[index : index + 76]}")
    print("metadata:")
    print("  attachment_render:")
    print(f"    scale: {args.scale}")
    print(f"    lines: {expected!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
