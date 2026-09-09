"""An embeddable reliability badge, and the one number it refuses to show alone.

A badge is the most-quoted surface a project has. It gets screenshotted, pasted
into slide decks and read by people who will never open the run behind it, which
makes it the worst possible place to publish a point estimate.

So this badge does two things differently from every other coverage-style badge:

- **The sample size is part of the label, always.** `92% (n=25)` and `92% (n=2)`
  are not the same claim, and a badge that renders them identically is lying by
  omission in the medium least able to carry a caveat.
- **The colour comes from the confidence interval's lower bound, not the rate.**
  A green badge should mean "the sample supports this", not "the point estimate
  happened to land high". Two passing runs out of two is 100% and supports
  almost nothing; its lower bound is around 0.34, so it renders amber.

Rendering is hand-rolled SVG with no dependency and no network call. `textLength`
plus `lengthAdjust` pins the text to the box the geometry reserved, so the output
is identical everywhere without this module needing font metrics for a font it
cannot see.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Thresholds applied to the interval's **lower bound**. Deliberately strict:
#: the question a badge answers is "can I rely on this", and the honest answer
#: from a small sample is "not yet", whatever the point estimate says.
GREEN = 0.90
AMBER = 0.70

COLOURS = {
    "green": "#2f7d32",
    "amber": "#a86b00",
    "red": "#b3261e",
    "grey": "#5f6368",
    "label": "#3c4043",
}

#: Below this, an interval is wide enough that the rate is not the story.
SMALL_SAMPLE = 30


def colour_for(lower_bound: float | None) -> str:
    """Badge colour from the lower bound. Unknown is grey, never green."""
    if lower_bound is None:
        return COLOURS["grey"]
    if lower_bound >= GREEN:
        return COLOURS["green"]
    if lower_bound >= AMBER:
        return COLOURS["amber"]
    return COLOURS["red"]


def summarise(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull the badge's inputs out of a `tooltrace benchmark --summary` payload."""
    overall = ((payload.get("summary") or {}).get("overall")) or {}
    runs = overall.get("n")
    rate = overall.get("rate")
    low, high = overall.get("ci_low"), overall.get("ci_high")
    agent = ((payload.get("config") or {}).get("agent")) or "agent"
    return {
        "agent": str(agent),
        "runs": int(runs) if isinstance(runs, int) else None,
        "rate": float(rate) if isinstance(rate, int | float) else None,
        "ci_low": float(low) if isinstance(low, int | float) else None,
        "ci_high": float(high) if isinstance(high, int | float) else None,
        "is_subset": bool((payload.get("selection") or {}).get("is_subset")),
    }


def message_for(facts: dict[str, Any]) -> str:
    """The badge's right-hand text. `n` is never optional."""
    if facts["rate"] is None or not facts["runs"]:
        return "not measured"
    return f"{facts['rate'] * 100:.0f}% (n={facts['runs']})"


def label_for(facts: dict[str, Any]) -> str:
    """The left-hand text. A subset says so: a trimmed run is not a full one."""
    base = "agent reliability"
    return f"{base} (subset)" if facts["is_subset"] else base


def _text_width(text: str) -> int:
    """Approximate rendered width in pixels at 11px.

    Only the box geometry depends on this; `textLength` then pins the glyphs to
    whatever box it produced, so being a few pixels out changes the padding and
    never clips or overflows.
    """
    narrow = set("iljtfr.,:;'|!()[]{}")
    wide = set("MWmw%")
    total = 0.0
    for char in text:
        total += 3.6 if char in narrow else 8.2 if char in wide else 6.4
    return int(total) + 10


def render_svg(facts: dict[str, Any]) -> str:
    """A self-contained SVG. No external font, no network, no script."""
    label = label_for(facts)
    message = message_for(facts)
    colour = colour_for(facts["ci_low"])
    label_w = _text_width(label)
    message_w = _text_width(message)
    total = label_w + message_w
    # The accessible name carries what the picture cannot: the interval, and
    # whether the sample supports the number at all.
    if facts["rate"] is None:
        alt = "Agent reliability: not measured."
    else:
        interval = (
            f", 95% confidence interval {facts['ci_low'] * 100:.0f}% to {facts['ci_high'] * 100:.0f}%"
            if facts["ci_low"] is not None and facts["ci_high"] is not None
            else ""
        )
        caveat = (
            f". Only {facts['runs']} runs, so this is a wide interval"
            if (facts["runs"] or 0) < SMALL_SAMPLE
            else ""
        )
        alt = f"{label}: {message}{interval}{caveat}."

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" '
        f'role="img" aria-label="{_escape(alt)}">'
        f"<title>{_escape(alt)}</title>"
        f'<rect width="{label_w}" height="20" rx="3" fill="{COLOURS["label"]}"/>'
        f'<rect x="{label_w}" width="{message_w}" height="20" rx="3" fill="{colour}"/>'
        f'<rect x="{label_w - 3}" width="6" height="20" fill="{COLOURS["label"]}"/>'
        f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{label_w / 2}" y="14" text-anchor="middle" '
        f'textLength="{label_w - 10}" lengthAdjust="spacingAndGlyphs">{_escape(label)}</text>'
        f'<text x="{label_w + message_w / 2}" y="14" text-anchor="middle" '
        f'textLength="{message_w - 10}" lengthAdjust="spacingAndGlyphs">{_escape(message)}</text>'
        f"</g></svg>"
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def render_endpoint(facts: dict[str, Any]) -> dict[str, Any]:
    """The shields.io `endpoint` payload, for anyone who prefers their renderer.

    Same rule about the colour: it is derived from the lower bound here too, so
    a shields-rendered badge cannot be greener than the sample supports.
    """
    colour = colour_for(facts["ci_low"])
    named = {v: k for k, v in COLOURS.items()}
    return {
        "schemaVersion": 1,
        "label": label_for(facts),
        "message": message_for(facts),
        "color": named.get(colour, "grey"),
    }


def embed_markdown(svg_url: str, page_url: str) -> str:
    """The snippet to paste into a README, with a link to the run behind it."""
    return f"[![Agent reliability]({svg_url})]({page_url})"


def from_summary_file(path: Path) -> dict[str, Any]:
    return summarise(json.loads(path.read_text(encoding="utf-8")))


def from_bundles(bundle_dirs: list[Path]) -> dict[str, Any]:
    """Badge facts computed directly from bundles, with a Wilson interval.

    Uses the project's own `wilson_interval` rather than a second formula, so a
    badge and a report can never disagree about the same runs.
    """
    from tooltrace.analysis.stats import wilson_interval
    from tooltrace.artifacts.bundles import load_bundle_result

    results = [load_bundle_result(b) for b in sorted(bundle_dirs)]
    if not results:
        return {
            "agent": "agent",
            "runs": 0,
            "rate": None,
            "ci_low": None,
            "ci_high": None,
            "is_subset": False,
        }
    successes = sum(1 for r in results if r.success)
    low, high = wilson_interval(successes, len(results))
    agents = sorted({r.agent for r in results})
    return {
        # Several agents in one badge would average away the thing being
        # measured, so the label says so instead of picking one.
        "agent": agents[0] if len(agents) == 1 else f"{len(agents)} agents",
        "runs": len(results),
        "rate": round(successes / len(results), 6),
        "ci_low": round(low, 6),
        "ci_high": round(high, 6),
        "is_subset": False,
    }
