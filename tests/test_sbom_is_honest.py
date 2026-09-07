"""The SBOM must describe this project, not the machine that built it.

The committed sbom.json listed 147 components against six declared runtime
dependencies, including `aihwbench` and `api-verity-lab` -- unrelated sibling
projects that happened to share the build environment. It also had no
serialNumber and no timestamp, so two copies could not be told apart.

An SBOM asserting false provenance is worse than no SBOM: it is the first
artifact a supply-chain reviewer checks.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _bom() -> dict:
    return json.loads((_ROOT / "sbom.json").read_text(encoding="utf-8"))


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared_runtime_deps() -> set[str]:
    with (_ROOT / "pyproject.toml").open("rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]
    return {_canonical(re.match(r"^[A-Za-z0-9._-]+", d).group(0)) for d in deps}


def test_sbom_is_identifiable() -> None:
    bom = _bom()
    assert bom.get("serialNumber"), "a BOM without a serialNumber cannot be compared"
    assert bom["metadata"].get("timestamp"), "a BOM without a timestamp has no provenance"
    assert bom["metadata"].get("tools"), "a BOM should record what produced it"


def test_sbom_lists_every_declared_runtime_dependency() -> None:
    listed = {c["name"] for c in _bom()["components"]}
    missing = sorted(_declared_runtime_deps() - listed)
    assert not missing, f"declared runtime dependencies absent from the SBOM: {missing}"


def test_sbom_contains_no_unrelated_projects() -> None:
    """The specific regression: sibling repos listed as dependencies."""
    listed = {c["name"] for c in _bom()["components"]}
    siblings = {"aihwbench", "api-verity-lab", "devrepro-doctor"}
    intruders = sorted(listed & siblings)
    assert not intruders, (
        f"the SBOM claims unrelated sibling projects as dependencies: {intruders}. "
        "This usually means it was generated from the whole interpreter rather "
        "than from the declared dependency closure."
    )


def test_sbom_is_not_a_dump_of_the_environment() -> None:
    """Bounded by what the project declares, not by what is installed.

    Exact size varies with the resolver, but a project with six runtime
    dependencies cannot legitimately have a hundred-plus component closure
    while its lockfile-free dependency set stays this small.
    """
    components = _bom()["components"]
    assert len(components) < 100, (
        f"{len(components)} components for {len(_declared_runtime_deps())} declared "
        "runtime dependencies -- this looks like an environment dump again"
    )


def test_sbom_version_matches_the_package() -> None:
    with (_ROOT / "pyproject.toml").open("rb") as fh:
        version = tomllib.load(fh)["project"]["version"]
    assert _bom()["metadata"]["component"]["version"] == version, (
        "the SBOM describes a different version of the project than pyproject does"
    )
