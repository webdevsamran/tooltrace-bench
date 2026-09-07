"""Generate a CycloneDX SBOM describing *this project's* dependency graph.

The previous version iterated `importlib.metadata.distributions()` -- every
package installed in the interpreter -- so the committed sbom.json listed 147
components against six declared runtime dependencies, including `aihwbench`
and `api-verity-lab`, which are unrelated sibling projects that happened to be
installed in the same environment. An SBOM asserting false provenance is worse
than none: it is the first artifact a supply-chain reviewer checks, and it
leaked the names of other local projects.

This resolves the closure of what the project actually declares, starting from
pyproject's `dependencies` and walking each package's own `Requires-Dist`. A
package that is installed but unreachable from those roots is not part of this
project's supply chain and is not listed.

Deterministic: given the same environment it produces byte-identical output
apart from `metadata.timestamp`, which callers can pin via SOURCE_DATE_EPOCH.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
import uuid
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+")


def _canonical(name: str) -> str:
    """PEP 503 normalization, so `PyYAML` and `pyyaml` are one component."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared_roots() -> list[str]:
    with (_ROOT / "pyproject.toml").open("rb") as fh:
        project = tomllib.load(fh)["project"]
    roots = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        roots.extend(extra)
    names = []
    for spec in roots:
        match = _NAME_RE.match(spec.strip())
        if match:
            names.append(_canonical(match.group(0)))
    return sorted(set(names))


def _requires(dist: metadata.Distribution) -> list[str]:
    """Runtime requirements of a distribution, excluding extras-only ones."""
    out = []
    for raw in dist.requires or []:
        # "foo (>=1.0) ; extra == 'dev'" -- extras are not installed by default.
        if "extra ==" in raw:
            continue
        match = _NAME_RE.match(raw.strip())
        if match:
            out.append(_canonical(match.group(0)))
    return out


def _resolve_closure(roots: list[str]) -> dict[str, str]:
    """Walk from the declared roots to every package they actually pull in."""
    installed = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            installed[_canonical(str(name))] = dist

    resolved: dict[str, str] = {}
    missing: list[str] = []
    queue = list(roots)
    seen = set(roots)
    while queue:
        name = queue.pop()
        dist = installed.get(name)
        if dist is None:
            missing.append(name)
            continue
        resolved[name] = str(dist.version)
        for dep in _requires(dist):
            if dep not in seen:
                seen.add(dep)
                queue.append(dep)
    if missing:
        print(
            "warning: declared or transitive dependencies are not installed, so "
            "they are absent from the SBOM: " + ", ".join(sorted(missing)),
            file=sys.stderr,
        )
    return resolved


def _framework_version() -> str:
    try:
        return str(metadata.version("tooltrace-bench"))
    except metadata.PackageNotFoundError:
        sys.path.insert(0, str(_ROOT))
        from tooltrace.core.versions import FRAMEWORK_VERSION

        return FRAMEWORK_VERSION


def build() -> dict[str, object]:
    roots = _declared_roots()
    resolved = _resolve_closure(roots)
    components = [
        {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
        }
        for name, version in sorted(resolved.items())
    ]
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    stamp = (datetime.fromtimestamp(int(epoch), UTC) if epoch else datetime.now(UTC)).replace(
        microsecond=0
    )
    version = _framework_version()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        # A BOM with no serial number or timestamp cannot be compared against
        # another copy of itself; both were absent before.
        "serialNumber": "urn:uuid:"
        + str(uuid.uuid5(uuid.NAMESPACE_URL, f"tooltrace-bench@{version}")),
        "version": 1,
        "metadata": {
            "timestamp": stamp.isoformat().replace("+00:00", "Z"),
            "tools": [{"vendor": "tooltrace-bench", "name": "generate_sbom.py"}],
            "component": {
                "type": "application",
                "name": "tooltrace-bench",
                "version": version,
                "purl": f"pkg:pypi/tooltrace-bench@{version}",
            },
        },
        "components": components,
    }


def main() -> int:
    bom = build()
    rendered = json.dumps(bom, indent=2) + "\n"
    (_ROOT / "sbom.json").write_text(rendered, encoding="utf-8")
    print(f"sbom.json written ({len(bom['components'])} components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
