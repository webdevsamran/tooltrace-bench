"""Generate a minimal CycloneDX-style SBOM from installed distributions.

Used as the deterministic fallback when cyclonedx-py is unavailable in CI.
Output: sbom.json with component name/version/purl for every installed dist.
"""

from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path


def _framework_version() -> str:
    try:
        return str(metadata.version("tooltrace-bench"))
    except metadata.PackageNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from tooltrace.core.versions import FRAMEWORK_VERSION

        return FRAMEWORK_VERSION


def main() -> int:
    components = []
    for dist in sorted(metadata.distributions(), key=lambda d: str(d.metadata["Name"])):
        name = str(dist.metadata["Name"])
        version = str(dist.version)
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
            }
        )
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "tooltrace-bench",
                "version": _framework_version(),
            }
        },
        "components": components,
    }
    Path("sbom.json").write_text(json.dumps(bom, indent=2), encoding="utf-8")
    print(f"sbom.json written ({len(components)} components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
