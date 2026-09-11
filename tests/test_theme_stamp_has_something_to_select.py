"""Stamping `data-theme="dark"` is inert if nothing in the stylesheet styles it.

`index.html` carries four lines of blocking script that set `data-theme` on the
root before the first paint, because `useTheme` in `web/src/App.tsx` does the
same thing one turn too late -- it runs in an effect, so a system-dark user
watched a white page flash to dark. `web/src/__tests__/theme.test.tsx` checks
that the script and the hook still agree with each other.

What that test could not check is the other end: whether the attribute it sets
selects anything. Vitest leaves CSS unprocessed, so a `?raw` or `?inline` import
of the stylesheet returns an empty string -- and only once some other file in
the run has already pulled the module in, so the assertion passed when run alone
and failed inside the suite. A result that depends on what else ran is one
nobody can act on, which is the argument `web/src/test-setup.ts` already makes
about this exact suite.

So the two claims that need the stylesheet live here, where reading a file is a
file read. This is the same split as `tests/test_vscode_extension_matches_the_cli.py`,
which parses JavaScript from Python for the same reason: the check belongs
wherever it can actually be made.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "web" / "src" / "styles.css"
INDEX = ROOT / "web" / "index.html"


def stylesheet() -> str:
    return CSS.read_text(encoding="utf-8")


def test_the_stylesheet_is_where_it_is_expected_to_be() -> None:
    """A moved file would make every assertion below vacuous rather than red."""
    assert CSS.is_file(), CSS
    assert len(stylesheet()) > 1000, "styles.css is suspiciously small"


def test_the_stamped_attribute_selects_a_real_rule() -> None:
    """`data-theme="dark"` has to match something or the script does nothing."""
    assert '[data-theme="dark"]' in stylesheet()


def test_light_is_the_unstamped_default() -> None:
    """A failed stamp degrades to light, not to an unstyled page.

    `localStorage` throws in some private modes, and the script swallows that
    deliberately. What it falls back to matters: the light palette has to be on
    bare `:root`, not on `[data-theme="light"]`.
    """
    css = stylesheet()
    assert re.search(r"^:root\s*\{", css, re.M), "no bare :root block carries the base palette"
    assert "color-scheme: light" in css


def test_every_value_the_script_can_stamp_is_styled() -> None:
    """Both branches of the script, not just the one that changes anything."""
    css = stylesheet()
    for value in re.findall(
        r"dataset\.theme = (?:dark \? )?'(\w+)'", INDEX.read_text(encoding="utf-8")
    ):
        if value == "light":
            # Light is the `:root` default rather than an explicit block, which
            # is checked above; an explicit block would also be fine.
            continue
        assert f'[data-theme="{value}"]' in css, f"nothing styles data-theme={value}"
