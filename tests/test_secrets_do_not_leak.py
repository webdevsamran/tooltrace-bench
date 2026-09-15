"""Secrets must not reach output, storage, or the process list.

Six CodeQL alerts landed on this repository, all `high`, three of them naming
this file's subject: clear-text logging in `cli/main.py` and clear-text storage
in `security/redaction.py`. Every one turned out to be a false positive for the
vulnerability it claimed -- the analyser cannot see through `report()` or
`redaction_report()` and assumed taint propagated.

"Assumed" is the operative word, in both directions. Nothing here *proved* the
key never reached the output, or that the redaction record never quoted what it
found. The properties were true by construction and unchecked, which is the same
state `Attachment` and `evaluate_policy` were in.

So they are checked now, with real secrets, asserting on the actual bytes:

- a verification key handed to `a2a-card` must not appear in its output;
- a redaction record must not quote the personal data it reports finding -- a
  report that did would *be* the disclosure it exists to prevent;
- the preferred way to pass a key must read it from the environment, because a
  secret in `argv` is readable by every process on the machine for as long as
  the command runs, and lands in shell history afterwards.

The third is the one CodeQL was right about in substance while wrong about the
mechanism, and it is the only one that needed a code change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.cli.main import main

# Synthetic, and the whole point of this file is that it never reaches an output
# stream. Marked per line rather than exempting the file, so a real key pasted in
# here later is still caught.
SECRET = "s3cr3t-value-nothing-should-print-a1b2c3"  # secret-scan: allow


@pytest.fixture
def card(tmp_path: Path) -> Path:
    path = tmp_path / "agent-card.json"
    path.write_text(
        json.dumps(
            {
                "name": "demo",
                "url": "https://agent.example.test",
                "version": "1.0.0",
                "capabilities": {},
                "skills": [],
            }
        ),
        encoding="utf-8",
    )
    return path


# --- a verification key must not come back out -------------------------------


def test_a_literal_key_never_appears_in_the_json_output(card: Path, capsys) -> None:
    main(["a2a-card", str(card), "--key", f"k1={SECRET}", "--json"])
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_a_literal_key_never_appears_in_the_human_output(card: Path, capsys) -> None:
    """The prose path prints a different set of fields, so it needs its own check."""
    main(["a2a-card", str(card), "--key", f"k1={SECRET}"])
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_an_env_key_never_appears_either(card: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("TTB_TEST_VERIFICATION_KEY", SECRET)
    main(["a2a-card", str(card), "--key-env", "k1=TTB_TEST_VERIFICATION_KEY", "--json"])
    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


# --- the environment form, which is the point --------------------------------


def test_the_environment_form_works(card: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("TTB_TEST_VERIFICATION_KEY", SECRET)
    code = main(["a2a-card", str(card), "--key-env", "k1=TTB_TEST_VERIFICATION_KEY", "--json"])
    capsys.readouterr()
    # The card declares no signature, so conformance fails on required fields;
    # what matters here is that the key was accepted rather than rejected.
    assert code in (0, 3)


def test_a_missing_variable_is_refused_by_name(card: Path, capsys, monkeypatch) -> None:
    """Silently treating an unset variable as an empty key would verify
    signatures against the empty string."""
    monkeypatch.delenv("TTB_TEST_ABSENT", raising=False)
    code = main(["a2a-card", str(card), "--key-env", "k1=TTB_TEST_ABSENT"])
    assert code != 0
    assert "TTB_TEST_ABSENT" in capsys.readouterr().err


def test_the_literal_form_says_what_it_costs(card: Path, capsys) -> None:
    """It still works -- breaking it would be worse -- and it says why not to."""
    main(["a2a-card", str(card), "--key", f"k1={SECRET}"])
    err = capsys.readouterr().err
    assert "command line" in err
    assert "--key-env" in err


def test_no_other_command_takes_a_raw_secret(capsys) -> None:
    """The project's rule, checked rather than remembered.

    `openai_compat`, `anthropic` and `gemini` all take the *name* of an
    environment variable. `a2a-card --key` was the one place that took the value,
    and it is now the only one that may -- with a warning.
    """
    import argparse

    from tooltrace.cli.main import build_parser

    parser = build_parser()
    groups = getattr(parser._subparsers, "_group_actions", [])
    subparsers = [g for g in groups if isinstance(g, argparse._SubParsersAction)]
    offenders = []
    for name, sub in subparsers[0].choices.items():
        for action in sub._actions:
            metavar = str(action.metavar or "")
            looks_like_a_credential = any(
                word in metavar for word in ("SECRET", "PASSWORD", "TOKEN")
            )
            allowed = (name, tuple(action.option_strings)) == ("a2a-card", ("--key",))
            if looks_like_a_credential and not allowed:
                offenders.append(f"{name} {action.option_strings}")
    assert offenders == [], f"these take a credential as an argument value: {offenders}"


# --- the redaction record must not quote what it found ------------------------


def test_the_redaction_record_never_quotes_the_data_it_reports(tmp_path: Path) -> None:
    """A report that printed the personal data it found would be the disclosure.

    `Finding` says so in a comment -- "Never the matched text" -- and nothing
    checked it. This does, against a bundle containing a real-looking email,
    card number and key.
    """
    from tooltrace.security.redaction import certificate, redaction_report, write_record

    bundle = tmp_path / "leaky.tooltrace"
    bundle.mkdir()
    planted = {
        "email": "victim.person@example.test",
        "card": "4111 1111 1111 1111",
        "key": "AKIAIOSFODNN7EXAMPLE",
    }
    (bundle / "result.json").write_text(
        json.dumps({"note": " ".join(planted.values())}), encoding="utf-8"
    )
    (bundle / "workspace.diff").write_text(planted["email"], encoding="utf-8")

    report = redaction_report(bundle)
    record = certificate([bundle], generated_at="2026-09-15T00:00:00Z")
    written = write_record(record, tmp_path / "out")

    # The report, the record and both files on disk -- the JSON one is what
    # CodeQL flagged, and the markdown one is the one a person actually reads.
    blob = (
        json.dumps(report)
        + json.dumps(record)
        + "".join(f.read_text(encoding="utf-8") for f in written)
    )
    leaked = [name for name, value in planted.items() if value in blob]
    assert leaked == [], f"the redaction record quotes the {leaked} it found"


def test_the_record_still_reports_that_it_found_something(tmp_path: Path) -> None:
    """The test above passes trivially if the scanner finds nothing at all."""
    from tooltrace.security.redaction import redaction_report

    bundle = tmp_path / "leaky.tooltrace"
    bundle.mkdir()
    (bundle / "result.json").write_text(
        json.dumps({"note": "reach me at victim.person@example.test"}), encoding="utf-8"
    )
    record = redaction_report(bundle)
    assert record["pii_findings"], "nothing was detected, so the leak check proves nothing"
