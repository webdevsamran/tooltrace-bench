"""The Dockerfile and devcontainer must be structurally sound.

These cannot be built here — no Docker daemon is available in this environment —
so CI builds the image and runs `tasks`/`doctor` inside it. What *can* be
checked without a daemon is checked, because a Dockerfile that installs from a
source tree instead of a built wheel would silently reintroduce the packaging
defect this project already shipped: schemas missing from the wheel, invisible
for three releases because every install anyone tried was editable with the
repository sitting beside it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_DOCKERFILE = _ROOT / "Dockerfile"
_DEVCONTAINER = _ROOT / ".devcontainer" / "devcontainer.json"
_DOCKERIGNORE = _ROOT / ".dockerignore"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    assert _DOCKERFILE.is_file(), "Dockerfile is missing"
    return _DOCKERFILE.read_text(encoding="utf-8")


def test_the_image_installs_a_built_wheel_not_the_source_tree(dockerfile: str) -> None:
    """Installing the source tree would hide the packaging defect again."""
    assert "python -m build --wheel" in dockerfile
    assert "pip install --no-cache-dir /tmp/*.whl" in dockerfile
    assert "pip install -e" not in dockerfile, "an editable install defeats the point"


def test_the_runtime_stage_carries_no_repository(dockerfile: str) -> None:
    """`Path(__file__).parents[2] / 'schemas'` must not resolve in the image."""
    runtime = dockerfile.split("AS runtime", 1)[1]
    assert "COPY schemas/" not in runtime
    assert "COPY tooltrace/" not in runtime


def test_the_build_fails_if_the_installed_wheel_cannot_load_its_packs(dockerfile: str) -> None:
    """The defect is caught at image build time, not at a user's first run."""
    assert "tooltrace tasks --json" in dockerfile


def test_the_image_does_not_run_as_root(dockerfile: str) -> None:
    """It executes code it did not write; container isolation needs a non-root user."""
    assert "USER tooltrace" in dockerfile
    assert dockerfile.rindex("USER tooltrace") < dockerfile.rindex("ENTRYPOINT")


def test_git_is_available_because_it_is_a_declared_tool(dockerfile: str) -> None:
    """`tooltrace/tools/process.py` registers a git tool; a task may allow it."""
    assert "git" in dockerfile.split("AS runtime", 1)[1]


def test_the_build_context_excludes_a_stale_packaged_schema_copy() -> None:
    """A local hatch build writes tooltrace/schema_data/; copying it in would mask a break."""
    assert _DOCKERIGNORE.is_file()
    ignored = _DOCKERIGNORE.read_text(encoding="utf-8")
    assert "tooltrace/schema_data/" in ignored
    assert ".git/" in ignored


def test_the_devcontainer_installs_both_toolchains() -> None:
    config = json.loads(_DEVCONTAINER.read_text(encoding="utf-8"))
    assert config["name"]
    post = config["postCreateCommand"]
    assert "pip install -e" in post, "contributors want an editable install"
    assert "npm ci" in post, "the frontend is part of the project"


def test_ci_builds_the_image_and_runs_it() -> None:
    """This is the only place the Dockerfile is actually executed."""
    workflow = yaml.safe_load((_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    steps = workflow["jobs"]["sandbox-docker"]["steps"]
    run_blocks = " ".join(str(s.get("run", "")) for s in steps)
    assert "docker build" in run_blocks
    assert "tooltrace-bench:ci tasks" in run_blocks, "building without running proves little"
