"""`tooltrace --version` works today; this keeps it working and honest.

The sibling project api-verity-lab carried `__version__ = "0.1.0"` in the
package while `pyproject.toml` said 0.2.0 — nothing tested the two against
each other, so the drift sat there. This repo prints FRAMEWORK_VERSION from
`tooltrace.core.versions`, which is a third place the number can be written
down; all three have to agree.
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest
from tooltrace.cli.main import main
from tooltrace.core.versions import FRAMEWORK_VERSION

PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def _declared_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def test_framework_version_matches_pyproject() -> None:
    assert _declared_version() == FRAMEWORK_VERSION


def test_version_flag_exits_zero_and_prints_the_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == FRAMEWORK_VERSION
