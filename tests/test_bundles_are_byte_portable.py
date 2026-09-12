"""A bundle must hash the same on every operating system.

The manifest carries a SHA-256 of every file in the bundle, taken over the bytes
on disk. `Path.write_text` applies the platform's newline translation, so a
bundle written on Windows contained CRLF and its checksums committed to CRLF --
and `tooltrace verify` then reported six checksum mismatches per bundle on every
Linux and macOS checkout, on bundles nobody had touched.

It was not caught locally, because locally everything is Windows. It was caught
by CI on the first push, which is the argument for running the suite on three
operating systems.

A benchmark artifact whose checksum depends on the machine that wrote it is not
reproducible, and reproducibility is the entire claim of the `.tooltrace`
format. So this is checked on every run, on the bundles that actually ship,
rather than left to the one platform that happens to disagree.

The `.gitattributes` half matters as much: `results/** -text` stops git
normalising on commit and translating on checkout. Without it, a correct writer
still produces a broken checkout.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
GITATTRIBUTES = ROOT / ".gitattributes"

CRLF = b"\r\n"


def bundles() -> list[Path]:
    return sorted(p for p in RESULTS.glob("*.tooltrace") if p.is_dir())


BUNDLES = bundles()


def test_there_are_bundles_to_check() -> None:
    """A checkout with no published bundles would pass everything below."""
    assert BUNDLES, "no .tooltrace bundles are committed, so nothing here is checked"


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda b: b.name[:40])
def test_no_file_in_a_bundle_contains_a_carriage_return(bundle: Path) -> None:
    """The specific byte that made these unverifiable off Windows."""
    offenders = [
        p.relative_to(bundle).as_posix()
        for p in sorted(bundle.rglob("*"))
        if p.is_file() and CRLF in p.read_bytes()
    ]
    assert offenders == [], (
        f"{bundle.name} contains CRLF in {offenders}; its checksums are then "
        "specific to the platform that wrote it"
    )


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda b: b.name[:40])
def test_every_declared_checksum_matches_the_bytes_on_disk(bundle: Path) -> None:
    """`verify` does this too. Doing it here names the file rather than the
    bundle, which is the difference between a diagnosis and a symptom."""
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    mismatches = []
    for name, declared in manifest["checksums"].items():
        actual = hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        if actual != declared:
            mismatches.append(name)
    assert mismatches == [], f"{bundle.name}: checksum mismatch in {mismatches}"


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda b: b.name[:40])
def test_a_crlf_translation_would_change_every_checksum(bundle: Path) -> None:
    """The test above passes trivially if the files have no newlines at all.

    This proves the check has teeth: translating to CRLF must break the
    checksums, which is exactly what a careless checkout does.
    """
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    changed = 0
    for name, declared in manifest["checksums"].items():
        raw = (bundle / name).read_bytes()
        if b"\n" not in raw:
            continue
        translated = hashlib.sha256(raw.replace(b"\n", CRLF)).hexdigest()
        if translated != declared:
            changed += 1
    assert changed > 0, (
        f"{bundle.name}: no file changes under CRLF translation, so the test above proves nothing"
    )


# --- the other half: git must not translate them either ----------------------


def test_gitattributes_exists() -> None:
    """A correct writer still produces a broken checkout without this."""
    assert GITATTRIBUTES.is_file(), "no .gitattributes; git will normalise on its own terms"


def test_published_artifacts_are_exempt_from_text_translation() -> None:
    rules = GITATTRIBUTES.read_text(encoding="utf-8")
    for path in ("results/**", "tests/fixtures/**"):
        assert f"{path} -text" in rules, f"{path} is not marked -text"


def test_source_is_normalised_so_the_exemption_is_deliberate() -> None:
    """`-text` on everything would also "work", by giving up.

    The point is that source normalises and artifacts do not, so the exemption
    reads as a decision rather than as an absent setting.
    """
    rules = GITATTRIBUTES.read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in rules
