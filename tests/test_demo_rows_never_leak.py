"""A connected console must show the server's data, never a fixture.

`web/src/pages/workspace/shared.tsx` has always opened with the claim "demo
rows never leak into data". Every page in that directory rendered its `DEMO_*`
constant unconditionally, and the DEMO badge was the *only* thing gated on
`isServerMode()` -- so an administrator who connected a real deployment saw an
invented user list, an invented approval queue, and invented workers, with the
badge suppressed precisely because a server *was* connected. The claim was
exactly backwards.

That happened because the rule lived in a comment. It now lives in
`ConsoleData`, which takes both halves and picks between them, and in this test,
which refuses a page that reaches around it.

Checked from Python rather than TypeScript for the same reason as
`tests/test_frontend_primitives_are_reachable.py`: the question is about every
file in a directory at once, and that is what a directory walk is for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "web" / "src" / "pages" / "workspace"
DEMO_DATA = ROOT / "web" / "src" / "pages" / "demoData.ts"
API = ROOT / "web" / "src" / "api.ts"

#: A fixture constant, however it is spelled.
#:
#: `DEMO_*` was the first pattern, and `policies.tsx` walked straight past it
#: with a local `POLICY_DEMO` that it rendered unconditionally -- the same bug
#: under a different variable name. A check that only catches the naming
#: convention catches only the developers who follow it.
DEMO_REF = re.compile(r"\b(?:DEMO_[A-Z_]+|[A-Z][A-Z_]*_DEMO)\b")


def pages() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(WORKSPACE.glob("*.tsx"))
        if path.name != "shared.tsx"
    }


PAGES = pages()


def test_there_are_pages_to_check() -> None:
    """An empty directory would make every test below pass vacuously."""
    assert len(PAGES) >= 8, sorted(PAGES)


@pytest.mark.parametrize("name", sorted(PAGES))
def test_a_page_using_demo_rows_chooses_between_them_and_live_data(name: str) -> None:
    """The rule, stated as a property rather than as a comment.

    A page may use a `DEMO_*` fixture only if it also decides, at render time,
    whether a server is connected -- either by handing both halves to
    `ConsoleData`, or by checking `isServerMode()` itself.
    """
    source = PAGES[name]
    if not DEMO_REF.search(source):
        return
    chooses = "ConsoleData" in source or "isServerMode()" in source
    assert chooses, (
        f"{name} renders {sorted(set(DEMO_REF.findall(source)))} with no idea whether a "
        "server is connected, so a real deployment would show invented rows"
    )


@pytest.mark.parametrize("name", sorted(PAGES))
def test_a_page_that_shows_demo_rows_also_shows_the_badge(name: str) -> None:
    """Invented data is acceptable; invented data that looks real is not.

    `ServerStatus` counts: it renders `<DemoBadge />` when no server is
    connected and the server's URL when one is, which is the same guarantee in
    the place a reader is already looking for the connection state.
    """
    source = PAGES[name]
    if not DEMO_REF.search(source):
        return
    badged = any(marker in source for marker in ("ConsoleData", "DemoBadge", "ServerStatus"))
    assert badged, f"{name} can show demo rows with no DEMO badge"


@pytest.mark.parametrize("name", sorted(PAGES))
def test_a_page_that_fetches_does_not_hand_the_table_a_fixture(name: str) -> None:
    """The specific shape of the original bug.

    `<DataTable rows={DEMO_USERS} …>` sitting next to a `isServerMode()` call
    that only decided whether to draw a badge. The fixture must reach the table
    through `ConsoleData` or through a branch, never as the literal `rows`.
    """
    source = PAGES[name]
    direct = re.findall(r"rows=\{((?:DEMO_[A-Z_]+|[A-Z][A-Z_]*_DEMO))\}", source)
    assert not direct, (
        f"{name} passes {direct} straight to a table; it would render on a connected server"
    )


# --- the fixtures themselves -------------------------------------------------


def test_every_fixture_is_typed_as_something_the_api_returns() -> None:
    """A preview may not promise a feature the product does not have.

    The baselines fixture had `scope`, `metric` and `tolerance` columns; the
    webhooks fixture had a health `status`; the workers fixture had a
    `utilization` ratio. None of those exist anywhere in this product, so
    somebody evaluating the console was being shown a roadmap as if it were a
    screenshot. Typing the fixtures against `api.ts` is what makes the compiler
    refuse that.
    """
    source = DEMO_DATA.read_text(encoding="utf-8")
    declared = re.findall(r"export const (DEMO_[A-Z_]+)\s*:\s*([A-Za-z]+)\[\]", source)
    untyped = re.findall(r"export const (DEMO_[A-Z_]+)\s*=", source)
    assert not untyped, f"these fixtures have no API type, so nothing checks them: {untyped}"
    assert len(declared) >= 5, declared

    api = API.read_text(encoding="utf-8")
    for fixture, type_name in declared:
        assert f"interface {type_name}" in api, (
            f"{fixture} is typed as `{type_name}`, which api.ts does not define -- "
            "so it is not a shape this server can actually return"
        )


def test_the_fixture_module_defines_no_shapes_of_its_own() -> None:
    """A local interface is how the drift started: it let the fixture describe
    a system nobody had built."""
    source = DEMO_DATA.read_text(encoding="utf-8")
    local = re.findall(r"export interface (Demo[A-Za-z]+)", source)
    assert local == [], f"demoData.ts invents its own shapes: {local}"


# --- the endpoints the pages depend on ---------------------------------------

#: page -> the client function it must call in server mode.
EXPECTED_LOADERS = {
    "users.tsx": "listUsers",
    "review.tsx": "listApprovals",
    "audit.tsx": "listAudit",
    "webhooks.tsx": "listWebhooks",
    "baselines.tsx": "listBaselines",
    "workers.tsx": "listWorkers",
}


@pytest.mark.parametrize("name", sorted(EXPECTED_LOADERS))
def test_the_page_actually_calls_the_server(name: str) -> None:
    loader = EXPECTED_LOADERS[name]
    assert loader in PAGES[name], f"{name} never calls `{loader}`"


@pytest.mark.parametrize("name", sorted(EXPECTED_LOADERS))
def test_the_loader_exists_and_hits_a_route_the_server_serves(name: str) -> None:
    """The other half of the same rot: a client function pointing at a path the
    server does not route returns a 404 the page renders as an error."""
    from tooltrace.server.core import ROUTES

    api = API.read_text(encoding="utf-8")
    loader = EXPECTED_LOADERS[name]
    match = re.search(
        rf"export async function {loader}\b.*?apiGet<[^>]*>\(\s*'([^']+)'", api, re.DOTALL
    )
    assert match, f"{loader} is not defined in api.ts, or does not call apiGet"
    path = match.group(1)
    assert ("GET", path) in ROUTES, f"{loader} calls {path}, which the server does not route"


def test_serverstatus_is_what_makes_it_count() -> None:
    """The test above accepts `ServerStatus` as a badge. This is why.

    If `ServerStatus` stopped rendering `DemoBadge`, every page relying on it
    would lose its badge and nothing else here would notice.
    """
    shared = (WORKSPACE / "shared.tsx").read_text(encoding="utf-8")
    body = shared[shared.index("export function ServerStatus") :]
    assert "DemoBadge" in body.split("export function")[0] or "DemoBadge" in body[:400]
