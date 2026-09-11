"""A deterministic PNG writer, so a vision task can carry a real image.

`Attachment` has been declarable since the v2 protocol was written -- "multimodal
attachment referenced by deterministic hash, never embedded" -- and nothing in
this repository ever read the field. A multimodal pack needs an actual image
before it needs anything else, and there were three ways to get one:

1. **Commit a binary.** A PNG in git that nobody can diff, whose contents no
   test can check against the answer the task claims is in it. The task says the
   error code is `0x8007000E`; the image says whatever it says.
2. **Depend on Pillow.** A C-extension image library, in a project whose
   dependency list is deliberately short and whose charts are hand-rolled SVG
   for exactly this reason.
3. **Generate it here.** ~200 lines of PNG encoder and a 5x7 bitmap font, no
   dependencies, and -- the point -- *reversible*: `decode_gray` reads the
   pixels back, so a test can re-render the text the task claims and assert the
   committed image is that image, pixel for pixel.

Option 3 is the only one where the image and the expected answer cannot drift
apart, which is the failure this repository keeps finding in itself.

**What this does not establish.** That a given vision model can read a 5x7
bitmap font is not measured here and is not claimed anywhere. An eval image a
model cannot read measures the renderer; the scale is configurable for that
reason, and `tests/test_multimodal_attachments.py` asserts what is actually
checkable -- that the pixels spell the answer.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence

#: Glyphs are 5 wide and 7 tall, one int per row, bit 4 (0b10000) leftmost.
GLYPH_WIDTH = 5
GLYPH_HEIGHT = 7

#: Uppercase, digits and the punctuation an error code or a form label needs.
#: Deliberately small: every glyph here is one somebody drew and checked, and a
#: font with a wrong glyph in it would put a wrong character in an image whose
#: whole purpose is to carry an exact string.
FONT: dict[str, tuple[int, int, int, int, int, int, int]] = {
    " ": (0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000),
    "A": (0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "B": (0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110),
    "C": (0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110),
    "D": (0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110),
    "E": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111),
    "F": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000),
    "G": (0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01111),
    "H": (0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "I": (0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b11111),
    "J": (0b00111, 0b00010, 0b00010, 0b00010, 0b00010, 0b10010, 0b01100),
    "K": (0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001),
    "L": (0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111),
    "M": (0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001),
    "N": (0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001),
    "O": (0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "P": (0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000),
    "Q": (0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10010, 0b01101),
    "R": (0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001),
    "S": (0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110),
    "T": (0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100),
    "U": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "V": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100),
    "W": (0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b11011, 0b10001),
    "X": (0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001),
    "Y": (0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100),
    "Z": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111),
    "0": (0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110),
    "1": (0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "2": (0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111),
    "3": (0b11111, 0b00010, 0b00100, 0b00010, 0b00001, 0b10001, 0b01110),
    "4": (0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010),
    "5": (0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110),
    "6": (0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110),
    "7": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000),
    "8": (0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110),
    "9": (0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100),
    ":": (0b00000, 0b00110, 0b00110, 0b00000, 0b00110, 0b00110, 0b00000),
    "-": (0b00000, 0b00000, 0b00000, 0b01110, 0b00000, 0b00000, 0b00000),
    ".": (0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00110, 0b00110),
    ",": (0b00000, 0b00000, 0b00000, 0b00000, 0b00110, 0b00110, 0b01100),
    "/": (0b00001, 0b00010, 0b00010, 0b00100, 0b01000, 0b01000, 0b10000),
    "#": (0b01010, 0b01010, 0b11111, 0b01010, 0b11111, 0b01010, 0b01010),
    "_": (0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b11111),
    "(": (0b00010, 0b00100, 0b01000, 0b01000, 0b01000, 0b00100, 0b00010),
    ")": (0b01000, 0b00100, 0b00010, 0b00010, 0b00010, 0b00100, 0b01000),
    "=": (0b00000, 0b00000, 0b11111, 0b00000, 0b11111, 0b00000, 0b00000),
    "+": (0b00000, 0b00100, 0b00100, 0b11111, 0b00100, 0b00100, 0b00000),
    "!": (0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00000, 0b00100),
    "?": (0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b00000, 0b00100),
    "'": (0b00100, 0b00100, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000),
}

WHITE = 255
BLACK = 0


class UnrenderableCharacter(ValueError):
    """A character the font has no glyph for.

    Raised rather than substituted. A missing glyph silently replaced by a blank
    would put an image in front of a model that does not say what the task
    claims it says, and the task would then be scoring the font.
    """


def unrenderable_characters(text: str) -> list[str]:
    return sorted({c for c in text if c.upper() not in FONT})


def render_grid(lines: Sequence[str], *, scale: int = 6, margin: int = 10) -> list[list[int]]:
    """Black text on white, as a grid of 8-bit greyscale values.

    `scale` is how many image pixels one font pixel becomes. It is a parameter
    rather than a constant because legibility to a model is the open question
    here: a 5x7 glyph at scale 1 is 5 pixels wide and nothing can read it.
    """
    if scale < 1:
        raise ValueError("scale must be at least 1")
    if margin < 0:
        raise ValueError("margin must not be negative")
    rows = [line.upper() for line in lines] or [""]
    for line in rows:
        missing = unrenderable_characters(line)
        if missing:
            raise UnrenderableCharacter(f"no glyph for {missing} in {line!r}")

    # One blank column between glyphs, and one blank row of font pixels between
    # lines, both scaled with everything else.
    columns = max(len(line) for line in rows)
    text_width = (columns * (GLYPH_WIDTH + 1) - 1) * scale if columns else 0
    text_height = (len(rows) * (GLYPH_HEIGHT + 2) - 2) * scale

    width = text_width + 2 * margin
    height = text_height + 2 * margin
    grid = [[WHITE] * width for _ in range(height)]

    for line_index, line in enumerate(rows):
        top = margin + line_index * (GLYPH_HEIGHT + 2) * scale
        for char_index, character in enumerate(line):
            glyph = FONT[character]
            left = margin + char_index * (GLYPH_WIDTH + 1) * scale
            for row, bits in enumerate(glyph):
                for column in range(GLYPH_WIDTH):
                    if not bits & (1 << (GLYPH_WIDTH - 1 - column)):
                        continue
                    for dy in range(scale):
                        target = grid[top + row * scale + dy]
                        start = left + column * scale
                        target[start : start + scale] = [BLACK] * scale
    return grid


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def encode_gray(grid: Sequence[Sequence[int]]) -> bytes:
    """An 8-bit greyscale PNG, filter type 0 on every scanline.

    The simplest legal PNG there is. Nothing here needs adaptive filtering, and
    a fixed filter keeps `decode_gray` small enough to be obviously correct --
    which matters, because the test that proves the image says what the task
    claims runs through it.
    """
    if not grid or not grid[0]:
        raise ValueError("grid must have at least one pixel")
    height = len(grid)
    width = len(grid[0])
    if any(len(row) != width for row in grid):
        raise ValueError("grid rows are not all the same length")

    raw = bytearray()
    for row in grid:
        raw.append(0)  # filter: none
        raw.extend(row)

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def render_text_png(lines: Sequence[str], *, scale: int = 6, margin: int = 10) -> bytes:
    return encode_gray(render_grid(lines, scale=scale, margin=margin))


def decode_gray(data: bytes) -> list[list[int]]:
    """Read back a PNG this module wrote.

    Not a general PNG decoder, and it says so by refusing anything else: any
    colour type but greyscale, any bit depth but 8, or any scanline filter but
    0 raises. A decoder that guessed would let a test pass against an image it
    had not actually understood.
    """
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    offset = 8
    width = height = 0
    compressed = bytearray()
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        tag = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if tag == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", payload[:10])
            if depth != 8 or colour != 0:
                raise ValueError(
                    f"only 8-bit greyscale is supported, got depth={depth} type={colour}"
                )
        elif tag == b"IDAT":
            compressed.extend(payload)
        elif tag == b"IEND":
            break
    if not width or not height:
        raise ValueError("PNG has no IHDR")

    raw = zlib.decompress(bytes(compressed))
    grid: list[list[int]] = []
    for y in range(height):
        start = y * (width + 1)
        filter_type = raw[start]
        if filter_type != 0:
            raise ValueError(f"scanline {y} uses filter {filter_type}; only 0 is supported")
        grid.append(list(raw[start + 1 : start + 1 + width]))
    return grid


_REVERSE_FONT: dict[tuple[int, ...], str] = {bits: char for char, bits in FONT.items()}


def _black_run_lengths(grid: Sequence[Sequence[int]]) -> list[int]:
    runs: list[int] = []
    for row in grid:
        run = 0
        for value in row:
            if value == BLACK:
                run += 1
            elif run:
                runs.append(run)
                run = 0
        if run:
            runs.append(run)
    return runs


def read_text(data: bytes, *, margin: int = 10, scale: int | None = None) -> list[str]:
    """Read back the lines :func:`render_text_png` drew. Not OCR.

    This is an exact inverse of a known renderer, not a reader of images in
    general: it slices the grid at the pitch the renderer used and looks each
    5x7 cell up in the font. A cell that is not a glyph raises, rather than
    being guessed at -- a reader that guessed would let the round-trip test pass
    against an image it had not actually understood, which is the whole property
    being checked.

    `scale` is inferred when not given, as the greatest common divisor of the
    black run lengths: every run is a whole number of font pixels wide, and real
    text contains single-pixel stems.
    """
    from math import gcd

    grid = decode_gray(data)
    height = len(grid)
    width = len(grid[0]) if grid else 0
    runs = _black_run_lengths(grid)
    if not runs:
        return [""]
    if scale is None:
        scale = 0
        for run in runs:
            scale = gcd(scale, run)
    if scale < 1:
        raise ValueError("could not infer a pixel scale from the image")

    span = width - 2 * margin + scale
    pitch = (GLYPH_WIDTH + 1) * scale
    if span <= 0 or span % pitch:
        raise ValueError(
            f"image is {width}px wide; that is not margin={margin} plus a whole "
            f"number of {GLYPH_WIDTH}x{GLYPH_HEIGHT} glyphs at scale {scale}"
        )
    columns = span // pitch

    line_pitch = (GLYPH_HEIGHT + 2) * scale
    vertical = height - 2 * margin + 2 * scale
    if vertical <= 0 or vertical % line_pitch:
        raise ValueError(f"image is {height}px tall; that is not a whole number of text lines")
    line_count = vertical // line_pitch

    lines: list[str] = []
    for line_index in range(line_count):
        top = margin + line_index * line_pitch
        characters: list[str] = []
        for char_index in range(columns):
            left = margin + char_index * pitch
            bits: list[int] = []
            for row in range(GLYPH_HEIGHT):
                value = 0
                for column in range(GLYPH_WIDTH):
                    if grid[top + row * scale][left + column * scale] == BLACK:
                        value |= 1 << (GLYPH_WIDTH - 1 - column)
                bits.append(value)
            key = tuple(bits)
            if key not in _REVERSE_FONT:
                raise ValueError(
                    f"cell at line {line_index}, column {char_index} is not a glyph in this font"
                )
            characters.append(_REVERSE_FONT[key])
        lines.append("".join(characters).rstrip())
    return lines


def dimensions(data: bytes) -> tuple[int, int]:
    """(width, height) from the IHDR, without decompressing the pixels."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height
