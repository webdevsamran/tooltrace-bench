"""Every declared runtime dependency must actually be imported.

`typer` and `rich` were declared as runtime dependencies from the first
release. The CLI is written with `argparse` and neither package is imported
anywhere in `tooltrace/`, `scripts/` or `tests/`. Every install paid to
download and resolve two packages the project never used, and `sbom.json` —
which is generated from the declared closure and is checked for honesty by
`tests/test_sbom_is_honest.py` — described a dependency surface wider than the
real one.

An SBOM that overstates the closure is a security artifact that is wrong in the
unsafe direction: it invites review of things that are not there while saying
nothing about what is.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

#: Distribution name -> the module it provides. Every declared runtime
#: dependency must appear here, so adding one forces an explicit decision about
#: where it is used rather than letting it drift in unnoticed.
DIST_TO_MODULE: dict[str, str] = {
    "pydantic": "pydantic",
    "PyYAML": "yaml",
    "jsonschema": "jsonschema",
    "httpx": "httpx",
}


def _declared_runtime_dependencies() -> list[str]:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    raw = data["project"]["dependencies"]
    names = []
    for spec in raw:
        name = spec.split(">=")[0].split("==")[0].split("[")[0].split("<")[0].strip()
        names.append(name)
    return names


def _imported_top_level_modules() -> set[str]:
    modules: set[str] = set()
    for path in (_ROOT / "tooltrace").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return modules


def test_the_mapping_covers_every_declared_dependency() -> None:
    undeclared = sorted(set(_declared_runtime_dependencies()) - set(DIST_TO_MODULE))
    assert not undeclared, (
        f"new runtime dependencies {undeclared} have no entry in DIST_TO_MODULE; "
        "add one so this test can check they are actually used"
    )


@pytest.mark.parametrize("dist", sorted(DIST_TO_MODULE))
def test_each_declared_dependency_is_imported(dist: str) -> None:
    if dist not in _declared_runtime_dependencies():
        pytest.skip(f"{dist} is no longer declared")
    module = DIST_TO_MODULE[dist]
    assert module in _imported_top_level_modules(), (
        f"{dist} is a declared runtime dependency but `{module}` is imported nowhere "
        "in tooltrace/. Either use it or drop it."
    )


def test_the_removed_packages_stay_removed() -> None:
    """`typer` and `rich` were declared for three releases and never imported."""
    declared = _declared_runtime_dependencies()
    imported = _imported_top_level_modules()
    for name in ("typer", "rich"):
        assert name not in declared or name in imported, (
            f"{name} is declared again; the CLI uses argparse, so either it is now "
            "genuinely used or the declaration is back to being decorative"
        )
