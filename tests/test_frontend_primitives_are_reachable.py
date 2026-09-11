"""Every interaction primitive has to be reached by something a user can do.

This repository's recurring defect, found about twenty-five times while building
the roadmap out, is code that exists, is correct, is tested, and that nothing
reaches: `Attachment` declared and never read, a whole file-queue fleet with no
caller, `pareto_frontier` with no non-test caller, `sign_bundle` producing
signatures nothing could ask for.

The design spec asks for four interaction primitives, and each was written here
before it had a home. A toast system nobody pushes to is a live region that
never speaks. A counter nobody renders is an animation nobody sees. Both would
pass their unit tests forever.

So the rule is checked rather than remembered: a primitive must be called from
outside its own module and outside the tests. Python rather than TypeScript
because the question is about the whole tree at once, and `grep` over a
directory is the natural shape of the answer -- the same reason
`tests/test_vscode_extension_matches_the_cli.py` reads JavaScript from here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"

#: primitive -> (module that defines it, what it is for)
PRIMITIVES = {
    "useViewTransition": ("motion.tsx", "cross-fade route changes"),
    "useToast": ("motion.tsx", "confirm an action that scrolled out of view"),
    "Counter": ("motion.tsx", "roll a number that changed"),
    "useBrush": ("brush.tsx", "drag a range on a chart"),
    "BrushControls": ("brush.tsx", "set the same range from the keyboard"),
}


def sources() -> dict[Path, str]:
    """Every shipped `.ts`/`.tsx` under `web/src`, tests excluded."""
    found = {}
    for path in sorted(WEB.rglob("*.ts*")):
        if "__tests__" in path.parts or path.name.endswith(".d.ts"):
            continue
        found[path] = path.read_text(encoding="utf-8")
    return found


SOURCES = sources()


def test_there_are_sources_to_search() -> None:
    """An empty tree would make every test below pass vacuously."""
    assert len(SOURCES) >= 10, sorted(p.name for p in SOURCES)


@pytest.mark.parametrize("name", sorted(PRIMITIVES))
def test_the_primitive_is_defined_where_it_is_claimed(name: str) -> None:
    module, _purpose = PRIMITIVES[name]
    source = (WEB / module).read_text(encoding="utf-8")
    assert f"export function {name}" in source, f"{name} is not exported from {module}"


@pytest.mark.parametrize("name", sorted(PRIMITIVES))
def test_something_a_user_can_reach_calls_it(name: str) -> None:
    """Defined and exported is not the same as reachable.

    The caller has to be a different file: a module that only calls itself is
    the dead code this test exists to catch, one indirection later.
    """
    module, purpose = PRIMITIVES[name]
    callers = [
        path.relative_to(WEB).as_posix()
        for path, text in SOURCES.items()
        if path.name != module and name in text
    ]
    assert callers, (
        f"nothing outside {module} uses `{name}` ({purpose}), so it is dead code "
        "with passing tests -- this project's most common defect"
    )


def test_the_toast_provider_is_mounted_above_the_app() -> None:
    """`useToast` outside a provider is a no-op by design, so a missing
    provider would silence every message without failing anything."""
    main = (WEB / "main.tsx").read_text(encoding="utf-8")
    assert "<ToastProvider>" in main


def test_the_routes_render_the_transitioning_location() -> None:
    """`useViewTransition` returns a location, and returning it is not enough.

    If `<Routes>` kept reading the router's live location the hook would run,
    the cross-fade would start, and the page would change underneath it -- the
    animation would be real and pointless.
    """
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    assert "<Routes location={rendered}>" in app


def test_the_brush_ships_with_its_keyboard_route() -> None:
    """A page that used the drag without the inputs would be a filter half its
    users cannot operate, and axe gates this build."""
    users = {
        path.relative_to(WEB).as_posix(): text
        for path, text in SOURCES.items()
        if "BrushControls" in text or "onBrush" in text
    }
    assert users, "nothing uses the brush at all"
    pages = {name: text for name, text in users.items() if name.startswith("pages/")}
    for name, text in pages.items():
        assert "BrushControls" in text, f"{name} wires a drag-brush with no keyboard equivalent"
