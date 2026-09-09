"""The "mypy (strict)" claim and the mypy config must move together.

Three artifacts asserted strict type checking — `CONTRIBUTING.md` twice, the
pull-request template, and a pre-commit hook literally named "mypy (strict)" —
while `[tool.mypy]` set no `strict` key at all and explicitly disabled
`warn_return_any`. The gate was weaker than every document describing it.

Raising the floor was the honest direction: the alternative was editing three
documents to advertise a *weaker* gate, in a repository whose thesis is that it
holds itself to what it publishes. This test is what stops the two drifting
apart again — the claim cannot be deleted without the config, and the config
cannot be relaxed without the claim.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"

_RELAXATIONS = ("disallow_", "warn_", "strict", "check_")


def _mypy_config() -> dict[str, object]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    tool = data.get("tool", {})
    assert isinstance(tool, dict)
    config = tool.get("mypy", {})
    assert isinstance(config, dict)
    return config


def test_mypy_is_configured_strict() -> None:
    assert _mypy_config().get("strict") is True, (
        "CONTRIBUTING.md, the PR template and the pre-commit hook all claim "
        "'mypy (strict)'. Either configure it or stop claiming it."
    )


def test_warn_return_any_is_not_disabled() -> None:
    """`strict` implies it; an explicit False would silently switch it back off."""
    assert _mypy_config().get("warn_return_any") is not False


def test_no_override_relaxes_strictness_for_this_package() -> None:
    """Per-module escape hatches would make the strict claim true but hollow."""
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    overrides = data.get("tool", {}).get("mypy", {}).get("overrides", [])
    offenders = []
    for override in overrides:
        modules = override.get("module", [])
        modules = [modules] if isinstance(modules, str) else modules
        if not any(str(m).startswith("tooltrace") for m in modules):
            continue  # third-party stub gaps are fine
        for key, value in override.items():
            if key.startswith(_RELAXATIONS) and value is False:
                offenders.append(f"{modules}: {key}={value}")
    assert offenders == [], f"strictness relaxed for first-party modules: {offenders}"


@pytest.mark.parametrize(
    ("relative", "needle"),
    [
        ("CONTRIBUTING.md", "mypy --strict"),
        (".github/PULL_REQUEST_TEMPLATE.md", "`mypy` (strict)"),
    ],
)
def test_the_documents_still_make_the_claim(relative: str, needle: str) -> None:
    assert needle in (_ROOT / relative).read_text(encoding="utf-8")


def test_the_pre_commit_hook_is_named_and_scoped_to_match_ci() -> None:
    config = yaml.safe_load((_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [h for repo in config["repos"] for h in repo.get("hooks", [])]
    mypy_hooks = [h for h in hooks if "mypy" in str(h.get("name", "")).lower()]
    assert mypy_hooks, "the pre-commit mypy hook disappeared"
    hook = mypy_hooks[0]
    assert hook["name"] == "mypy (strict)"
    # CI runs `mypy tooltrace`; the hook must not check a narrower surface and
    # let something through locally that CI would then reject.
    assert hook.get("files") == "^tooltrace/"
