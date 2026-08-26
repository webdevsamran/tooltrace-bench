"""Targeted tests raising coverage of CLI, SDK, repro, security, scoring,
perturbations, failure classification and remaining adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.core.models import TraceEvent

from tests.conftest import make_task


def _ev(type_: str, payload: dict) -> TraceEvent:
    return TraceEvent(timestamp="t", seq=1, type=type_, payload=payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------


class TestRepro:
    def _make_bundle(self, tmp_path: Path) -> Path:
        from tooltrace.bundles import write_bundle
        from tooltrace.runners.runner import TaskRunner

        task = make_task()
        runner = TaskRunner()
        result, events, diff = runner.run(
            task,
            "scripted",
            {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "BAR"}}]},
            run_id="rep1",
        )
        return write_bundle(tmp_path / "b", result, events, task, diff, {})

    def test_reproduce_full_cycle(self, tmp_path) -> None:
        from tooltrace.bundles_repro import reproduce_bundle

        bundle = self._make_bundle(tmp_path)
        report = reproduce_bundle(bundle, out_dir=tmp_path / "out", rerun=True)
        assert report.verified and report.rerun_success
        assert report.new_bundle
        assert "match" in report.message or "differ" in report.message

    def test_reproduce_no_rerun(self, tmp_path) -> None:
        from tooltrace.bundles_repro import reproduce_bundle

        bundle = self._make_bundle(tmp_path)
        report = reproduce_bundle(bundle, rerun=False)
        assert report.verified and not report.rerun_attempted

    def test_reproduce_tampered_refuses(self, tmp_path) -> None:
        from tooltrace.bundles_repro import reproduce_bundle

        bundle = self._make_bundle(tmp_path)
        (bundle / "result.json").write_text("{}", encoding="utf-8")
        report = reproduce_bundle(bundle)
        assert not report.verified and report.problems

    def test_promote_trust_and_require_verified(self, tmp_path) -> None:
        from tooltrace.bundles_repro import promote_trust, require_verified
        from tooltrace.core.exceptions import BundleError
        from tooltrace.core.models import TrustState

        bundle = self._make_bundle(tmp_path)
        promote_trust(bundle, TrustState.REPRODUCED)
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["trust_state"] == "REPRODUCED"
        require_verified(bundle)  # ok

        (bundle / "scoring.json").write_text("{}", encoding="utf-8")
        with pytest.raises(BundleError):
            require_verified(bundle)


# ---------------------------------------------------------------------------


class TestScanRepo:
    def test_scan_finds_and_clean(self, tmp_path) -> None:
        from tooltrace.security.scan_repo import main, scan

        dirty = tmp_path / "dirty.py"
        dirty.write_text(
            'key = "sk-dummyabcdefghijklmnopqrstuvwxyz123456"' + chr(10), encoding="utf-8"
        )
        findings = scan([dirty])
        assert findings and findings[0][1]

        clean = tmp_path / "clean.py"
        clean.write_text("x = 1" + chr(10), encoding="utf-8")
        assert scan([clean]) == []

        assert main([str(clean)]) == 0
        assert main([str(dirty)]) == 9

    def test_skips_binary_and_vendor(self, tmp_path) -> None:
        from tooltrace.security.scan_repo import scan

        vendor = tmp_path / "node_modules" / "x.js"
        vendor.parent.mkdir(parents=True)
        vendor.write_text(
            "token = 'Bearer dummyabcdefghijklmnopqrstuvwxyz123456'" + chr(10), encoding="utf-8"
        )
        assert scan([tmp_path]) == []
