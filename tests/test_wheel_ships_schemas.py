"""The built wheel must work without a repository checkout.

This repository shipped a wheel in which *no task could be loaded at all*: the
schemas were never packaged, and the code path that looks for the packaged copy
was excluded from coverage. Testing the source tree could not have caught it,
because in a source tree the repo-root ``schemas/`` directory resolves.

So the test builds a real wheel, extracts it outside the repository, and runs
the call that used to raise. It is marked ``slow`` because it invokes a build;
the cross-platform and multi-version CI jobs deselect it, and the main
``python`` job runs ``scripts/wheel_check.py`` directly.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.slow


def _wheel_check() -> Any:
    path = _ROOT / "scripts" / "wheel_check.py"
    spec = importlib.util.spec_from_file_location("wheel_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, Path, Path]:
    module = _wheel_check()
    if shutil.which("python") is None and not Path(module.sys.executable).exists():
        pytest.skip("no interpreter available to build with")
    try:
        import build  # noqa: F401
        import hatchling  # noqa: F401
    except ImportError:  # pragma: no cover - only when dev extras are absent
        pytest.skip("build/hatchling not installed; `pip install -e '.[dev]'`")
    work = tmp_path_factory.mktemp("wheel")
    wheel = module.build_wheel(work / "dist")
    return module, wheel, work


def test_the_wheel_carries_the_schemas_byte_for_byte(built: tuple[Any, Path, Path]) -> None:
    module, wheel, _ = built
    assert module.check_wheel_payload(wheel) == []


def test_an_extracted_wheel_loads_every_task_with_no_checkout(
    built: tuple[Any, Path, Path],
) -> None:
    module, wheel, work = built
    assert module.check_extracted_wheel_runs(wheel, work / "run") == []


def test_the_payload_check_is_not_vacuous(built: tuple[Any, Path, Path], tmp_path: Path) -> None:
    """A wheel without the schemas must be reported, or the check proves nothing."""
    import zipfile

    module, wheel, _ = built
    stripped = tmp_path / "stripped.whl"
    with zipfile.ZipFile(wheel) as src, zipfile.ZipFile(stripped, "w") as dst:
        for item in src.infolist():
            if "schema_data" not in item.filename:
                dst.writestr(item, src.read(item.filename))
    problems = module.check_wheel_payload(stripped)
    assert problems, "stripping the schemas out of the wheel was not detected"
    assert any("task.schema.json" in p for p in problems)
