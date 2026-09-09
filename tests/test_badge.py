"""A badge is the most-quoted number a project has, so it gets the most caveats.

Badges are screenshotted, pasted into decks and read by people who will never
open the run behind them. That makes a badge the worst possible place to publish
a bare point estimate, and it is why this one differs from the usual
coverage-style badge in two ways that these tests exist to lock down:

- **`n` is always in the message.** `92% (n=25)` and `92% (n=2)` are different
  claims and a badge that renders them identically lies by omission.
- **Colour comes from the interval's lower bound, not the rate.** Two passes out
  of two is 100% and supports almost nothing; its lower bound is about 0.34. A
  green badge has to mean "the sample supports this".

The second rule is the one worth guarding, because the tempting implementation —
colour from the rate — looks right and is wrong in exactly the cases where a
badge does the most damage.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest
from tooltrace.cli.main import main
from tooltrace.reports.badge import (
    AMBER,
    COLOURS,
    GREEN,
    colour_for,
    embed_markdown,
    from_bundles,
    message_for,
    render_endpoint,
    render_svg,
    summarise,
)

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "results"


def facts(**over: object) -> dict:
    base = {
        "agent": "scripted",
        "runs": 100,
        "rate": 0.95,
        "ci_low": 0.92,
        "ci_high": 0.98,
        "is_subset": False,
    }
    base.update(over)
    return base


# --- colour comes from the lower bound --------------------------------------


def test_a_perfect_rate_over_two_runs_is_not_green() -> None:
    """The case the obvious implementation gets wrong.

    100% of 2 runs has a Wilson lower bound near 0.34. Rendering that green
    would put "perfectly reliable" on a claim two samples cannot support.
    """
    assert colour_for(0.34) == COLOURS["red"]
    assert colour_for(0.34) != COLOURS["green"]


def test_a_perfect_rate_over_many_runs_is_green() -> None:
    assert colour_for(0.97) == COLOURS["green"]


def test_the_thresholds_are_on_the_bound_not_the_estimate() -> None:
    assert colour_for(GREEN) == COLOURS["green"]
    assert colour_for(GREEN - 0.01) == COLOURS["amber"]
    assert colour_for(AMBER) == COLOURS["amber"]
    assert colour_for(AMBER - 0.01) == COLOURS["red"]


def test_an_unknown_bound_is_grey_never_green() -> None:
    """Unmeasured must never be the colour that means "good"."""
    assert colour_for(None) == COLOURS["grey"]


# --- the sample size is never dropped ---------------------------------------


def test_the_message_always_carries_n() -> None:
    assert message_for(facts(rate=0.92, runs=25)) == "92% (n=25)"
    assert message_for(facts(rate=0.92, runs=2)) == "92% (n=2)"


def test_no_runs_is_not_measured_rather_than_zero_percent() -> None:
    # 0% would read as a total failure; there was no measurement at all.
    assert message_for(facts(rate=None, runs=0)) == "not measured"
    assert message_for(facts(rate=0.5, runs=0)) == "not measured"


def test_a_subset_says_so_in_the_label() -> None:
    """A trimmed CI run must never be mistaken for a full one."""
    assert "subset" in render_svg(facts(is_subset=True))
    assert "subset" not in render_svg(facts(is_subset=False))


# --- the SVG itself ---------------------------------------------------------


def test_the_svg_is_well_formed_xml() -> None:
    root = ElementTree.fromstring(render_svg(facts()))
    assert root.tag.endswith("svg")


def test_the_svg_carries_no_script_and_no_external_reference() -> None:
    """A badge is embedded in other people's pages. It must be inert."""
    svg = render_svg(facts())
    assert "<script" not in svg.lower()
    assert "http://" not in svg.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in svg


def test_the_accessible_name_carries_what_the_picture_cannot() -> None:
    svg = render_svg(facts(rate=1.0, runs=2, ci_low=0.34, ci_high=1.0))
    root = ElementTree.fromstring(svg)
    label = root.get("aria-label") or ""
    assert "confidence interval" in label
    assert "wide interval" in label


def test_a_large_sample_does_not_claim_a_wide_interval() -> None:
    svg = render_svg(facts(runs=500, ci_low=0.94, ci_high=0.97))
    assert "wide interval" not in svg


def test_the_geometry_leaves_room_for_the_text() -> None:
    root = ElementTree.fromstring(render_svg(facts(rate=0.5, runs=1234)))
    width = int(root.get("width") or 0)
    boxes = [int(r.get("width") or 0) for r in root if r.tag.endswith("rect")]
    # The two panels tile the badge exactly; the separator overlays them.
    assert boxes[0] + boxes[1] == width


def test_text_is_pinned_to_its_box_so_any_font_renders_the_same() -> None:
    svg = render_svg(facts())
    assert svg.count('lengthAdjust="spacingAndGlyphs"') == 2


def test_content_is_escaped() -> None:
    svg = render_svg(facts(agent='<script>"'))
    assert "<script>" not in svg


# --- the shields endpoint agrees with the SVG -------------------------------


def test_the_endpoint_colour_matches_the_svg_rule() -> None:
    """Otherwise a shields-rendered badge could be greener than ours."""
    for low, expected in ((0.95, "green"), (0.8, "amber"), (0.2, "red"), (None, "grey")):
        assert render_endpoint(facts(ci_low=low))["color"] == expected


def test_the_endpoint_message_also_carries_n() -> None:
    assert "n=25" in render_endpoint(facts(runs=25))["message"]


# --- reading real inputs ----------------------------------------------------


def test_it_reads_a_benchmark_summary() -> None:
    payload = {
        "config": {"agent": "my-agent"},
        "summary": {"overall": {"n": 20, "rate": 0.9, "ci_low": 0.7, "ci_high": 0.97}},
        "selection": {"is_subset": True},
    }
    got = summarise(payload)
    assert got == {
        "agent": "my-agent",
        "runs": 20,
        "rate": 0.9,
        "ci_low": 0.7,
        "ci_high": 0.97,
        "is_subset": True,
    }


def test_a_summary_with_no_overall_block_is_not_measured() -> None:
    assert message_for(summarise({})) == "not measured"


def test_it_reads_this_repositorys_own_bundles() -> None:
    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles")
    got = from_bundles(bundles)
    assert got["runs"] == len(bundles)
    assert got["ci_low"] is not None and got["ci_low"] < 1.0, (
        "a finite sample cannot have a lower bound of 1.0"
    )


def test_the_interval_is_this_projects_own_wilson_function() -> None:
    """A second formula in a second place would eventually disagree."""
    from tooltrace.analysis.stats import wilson_interval

    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles")
    got = from_bundles(bundles)
    successes = round(got["rate"] * got["runs"])
    low, high = wilson_interval(successes, got["runs"])
    assert (got["ci_low"], got["ci_high"]) == (round(low, 6), round(high, 6))


def test_several_agents_are_not_averaged_into_one_name() -> None:
    """Averaging two agents into one badge would hide the comparison."""
    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles")
    got = from_bundles(bundles)
    assert got["agent"] == "scripted"


def test_no_bundles_is_not_measured_not_a_crash(tmp_path: Path) -> None:
    got = from_bundles([])
    assert got["rate"] is None
    assert message_for(got) == "not measured"


# --- the embed snippet ------------------------------------------------------


def test_the_embed_links_the_badge_to_the_run_behind_it() -> None:
    snippet = embed_markdown("https://example.test/badge.svg", "https://example.test/leaderboard")
    assert snippet.startswith("[![")
    assert "https://example.test/leaderboard" in snippet


# --- the CLI ----------------------------------------------------------------


def test_the_cli_writes_an_svg_and_an_endpoint(tmp_path: Path) -> None:
    if not list(_RESULTS.glob("*.tooltrace")):
        pytest.skip("no committed bundles")
    out = tmp_path / "badge" / "reliability.svg"
    assert main(["badge", "--bundles", str(_RESULTS), "--out", str(out)]) == 0
    assert out.is_file()
    endpoint = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert endpoint["schemaVersion"] == 1


def test_the_cli_prints_the_svg_when_no_output_is_given(capsys) -> None:
    if not list(_RESULTS.glob("*.tooltrace")):
        pytest.skip("no committed bundles")
    assert main(["badge", "--bundles", str(_RESULTS)]) == 0
    assert capsys.readouterr().out.lstrip().startswith("<svg")


def test_the_cli_needs_an_input(capsys) -> None:
    assert main(["badge"]) != 0
    assert "needs --summary or --bundles" in capsys.readouterr().err


def test_the_published_badge_matches_the_published_dataset() -> None:
    """The badge on the site must not drift from the runs it describes."""
    published = _ROOT / "web" / "public" / "badge" / "reliability.svg"
    results = _ROOT / "web" / "public" / "data" / "results.json"
    if not published.is_file() or not results.is_file():
        pytest.skip("no generated web data")
    rows = json.loads(results.read_text(encoding="utf-8"))
    match = re.search(r"n=(\d+)", published.read_text(encoding="utf-8"))
    assert match, "the published badge does not state a sample size"
    assert int(match.group(1)) == len(rows)
