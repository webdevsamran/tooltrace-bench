"""Every documented way to use this repository's own action must actually work.

`tests/test_github_action_is_usable.py` reads `action.yml` and checks its shape:
inputs documented, outputs wired to a step, no third-party actions pulled in on
a caller's behalf. Every one of those tests passed while the documented recipe
was broken twice over, because shape is not reachability:

1. `docs/recipes.md` said `uses: webdevsamran/tooltrace-bench@v0.3.0`. That tag
   is the only release this project has ever cut, it predates the action, and it
   contains no `action.yml` at all. A caller copying the recipe got
   "Can't find 'action.yml'" before a single task ran.
2. The action's `install` input defaults to true and its `version` input
   defaults to `tooltrace-bench`, so the default path is
   `pip install tooltrace-bench` -- a 404, because publishing is gated behind a
   repository variable that has never been set.

Neither is visible from inside the file. Both are one HTTP request away.

Two rules, and both go quiet on their own once the project ships:

- a documented `uses:` reference to this repository must resolve to a ref whose
  tree contains `action.yml`;
- while the distribution is absent from PyPI, a documented recipe must not rely
  on the action installing it -- it has to pass `install: false` or point
  `version:` at a source checkout.

Resolving refs and checking a package index need the network, so this runs in
CI beside `check_action_pins.py` rather than in the unit-test suite.
`GITHUB_TOKEN` lifts the API rate limit from 60/hour to 5000.

    python scripts/check_action_refs.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: This repository, as a caller writes it in a `uses:` line. A fork that renames
#: itself and rewrites its recipes has to change this line too; the alternative
#: is parsing `git remote`, which is absent in some CI checkouts and would make
#: the check silently skip rather than fail.
SELF = "webdevsamran/tooltrace-bench"

#: The distribution name the action installs by default.
DISTRIBUTION = "tooltrace-bench"

#: Markdown files a user is expected to copy from.
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]

USES_SELF = re.compile(rf"^\s*-?\s*uses:\s*{re.escape(SELF)}@(?P<ref>[\w.\-/]+)", re.IGNORECASE)

#: A fenced block's `with:` mapping, used to tell a recipe that opts out of the
#: install from one that silently relies on it.
INSTALL_FALSE = re.compile(r"^\s*install:\s*[\"']?false[\"']?\s*$", re.IGNORECASE)
VERSION_FROM_SOURCE = re.compile(r"^\s*version:\s*.*(?:git\+|@\s*git)", re.IGNORECASE)


def _get_json(url: str) -> object | None:
    """GET `url`, returning None for 404 and for any transport failure."""
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "check-action-refs"},
    )
    # Compare the parsed host, never a substring. `"api.github.com" in url` is
    # true of `https://elsewhere.example/?x=api.github.com`, and what hangs off
    # this test is whether a credential is attached -- so the loose form is a
    # token-disclosure bug waiting for the day the URL stops being a literal.
    # CodeQL flagged exactly this, and unlike the three alerts recorded in
    # SECURITY.md it was right about the mechanism.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and urllib.parse.urlsplit(url).hostname == "api.github.com":
        request.add_header("Authorization", f"Bearer {token}")
    try:
        # Fixed https hosts, built below from literals.
        with urllib.request.urlopen(request, timeout=30) as response:
            payload: object = json.load(response)
            return payload
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"warning: {url} returned HTTP {exc.code}", file=sys.stderr)
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"warning: could not reach {url}: {exc}", file=sys.stderr)
        raise


def ref_has_action(ref: str) -> bool:
    """True when `action.yml` exists in this repository at `ref`."""
    return (
        _get_json(f"https://api.github.com/repos/{SELF}/contents/action.yml?ref={ref}") is not None
    )


def is_published(distribution: str) -> bool:
    return _get_json(f"https://pypi.org/pypi/{distribution}/json") is not None


def recipes(path: Path) -> list[tuple[int, str, bool]]:
    """Each `uses:` of this repo in `path`, as (line number, ref, opts out)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    found = []
    for index, line in enumerate(lines):
        match = USES_SELF.match(line)
        if not match:
            continue
        # The step's own block: everything more-indented that follows, which is
        # where `with:` lives. A blank line or a fence ends it.
        indent = len(line) - len(line.lstrip())
        opts_out = False
        for following in lines[index + 1 :]:
            if not following.strip() or following.lstrip().startswith("```"):
                break
            if len(following) - len(following.lstrip()) <= indent:
                break
            if INSTALL_FALSE.match(following) or VERSION_FROM_SOURCE.match(following):
                opts_out = True
        found.append((index + 1, match.group("ref"), opts_out))
    return found


def main() -> int:
    try:
        published = is_published(DISTRIBUTION)
    except Exception:  # reported above; a flaky index is not a build failure
        print("could not reach PyPI; skipping the install-path rule", file=sys.stderr)
        published = True

    broken: list[str] = []
    assumes_pypi: list[str] = []
    checked = 0

    for path in DOCS:
        if not path.is_file():
            continue
        for lineno, ref, opts_out in recipes(path):
            where = f"{path.relative_to(ROOT).as_posix()}:{lineno}"
            checked += 1
            try:
                present = ref_has_action(ref)
            except Exception:  # reported above
                print(f"warning: could not resolve {where} ({ref})", file=sys.stderr)
                continue
            if not present:
                broken.append(f"{where}  {SELF}@{ref} has no action.yml at that ref")
            if not published and not opts_out:
                assumes_pypi.append(
                    f"{where}  relies on the action running "
                    f"`pip install {DISTRIBUTION}`, which is not on PyPI"
                )

    for problem in broken + assumes_pypi:
        print(f"error: {problem}", file=sys.stderr)

    if broken or assumes_pypi:
        print(
            "\nA recipe that fails before the benchmark starts is worse than no "
            "recipe: it reads as a working integration.",
            file=sys.stderr,
        )
        return 1

    state = "on PyPI" if published else "not on PyPI yet"
    print(f"checked {checked} documented reference(s) to {SELF}; {DISTRIBUTION} is {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
